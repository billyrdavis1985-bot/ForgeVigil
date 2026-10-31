"""One-file antivirus scan with a fixed, bounded engine invocation.

The operator explicitly selects one local file. This module resolves the
engine from trusted installation locations only, invokes exactly one custom
scan with a fixed argument list and no shell, binds the outcome to the exact
scanned bytes, and reports one of six outcomes. It never elevates, remediates,
updates signatures, alters policy, retries, or cancels unrelated scans.

Outcome contract (see SCANNING.md for evidence rules):
- DETECTED: the engine reported a detection for the exact bytes.
- NO_DETECTION_REPORTED: a completed scan tied to the exact bytes reported
  no detection. Never means guaranteed safe.
- UNAVAILABLE: no usable engine (missing, unsupported platform, or the
  invocation itself could not start).
- FAILED: the scan ran but its result cannot be interpreted reliably.
- TIMED_OUT_UNKNOWN: the wait bound expired. Completion and any underlying
  service activity are unknown. No retry, no global cancellation.
- INPUT_CHANGED_OR_UNSCANNABLE: the input changed before/during the scan,
  or could not be read or staged.

Exit-code honesty: engine exit 0 can mean "no malware" OR "malware found and
remediated". A clean outcome additionally requires the engine's own
no-threat marker in its output; anything else stays FAILED.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import subprocess
import sys
import time
import warnings

from .versions import SCAN_SCHEMA_VERSION

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
DEFAULT_TIMEOUT_S = 600.0
MIN_TIMEOUT_S = 1.0
MAX_TIMEOUT_S = 3600.0
MAX_EVIDENCE_LINES = 8
MAX_EVIDENCE_LINE_CHARS = 300

DETECTED = "detected"
NO_DETECTION_REPORTED = "no_detection_reported"
UNAVAILABLE = "unavailable"
FAILED = "failed"
TIMED_OUT_UNKNOWN = "timed_out_unknown"
INPUT_CHANGED_OR_UNSCANNABLE = "input_changed_or_unscannable"

DECISIVE_OUTCOMES = frozenset({DETECTED, NO_DETECTION_REPORTED})

# Fixed custom-scan tail. The engine path itself is resolved, never searched.
SCAN_ARGV_TAIL = ("-Scan", "-ScanType", "3", "-File")

_CLEAN_MARKER = "found no threats"
_FAILURE_MARKER = "failed with hr"
_HR_TOKEN = re.compile(r"0[xX][0-9a-fA-F]{1,16}")
_THREAT_WORD = re.compile(r"\bthreat\b", re.IGNORECASE)
_ENGINE_FILENAME = "mpcmdrun.exe"
_CLOUD_BOUNDARY = (
    "Local invocation only. This report does not establish offline processing: "
    "device cloud-protection and sample-submission settings apply independently."
)


class ScanError(Exception):
    """The scan cannot start. Carries a short machine code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _is_reserved_name(part: str) -> bool:
    """Windows reserved-name check without deprecated APIs.

    ntpath.isreserved exists on every platform; the pathlib spelling is
    deprecated on 3.14 and gone on 3.15. The fallback covers interpreters
    predating ntpath.isreserved.
    """
    isreserved = getattr(ntpath, "isreserved", None)
    if isreserved is not None:
        return bool(isreserved(part))
    import pathlib

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return bool(pathlib.PureWindowsPath(part).is_reserved())


def _is_windows() -> bool:
    return os.name == "nt" or sys.platform == "win32"


def input_path(raw: str) -> str:
    """Validate an operator-supplied scan target. Returns an absolute path.

    Relative paths are refused: the engine resolves them unreliably (observed
    engine failure on a relative target). Symlinks, reparse points,
    directories, and oversized files are refused before any invocation.
    """
    if not raw or not raw.strip() or len(raw) > 32767:
        raise ScanError("SCAN_INPUT_INVALID", "empty or oversized path")
    if _is_windows():
        lowered = raw.lower()
        if lowered.startswith(("\\\\.\\", "\\\\?\\")):
            raise ScanError("SCAN_INPUT_INVALID", "device path")
        import pathlib

        parts = pathlib.PureWindowsPath(raw).parts
        anchor = pathlib.PureWindowsPath(raw).anchor
        rest = parts[1:] if anchor else parts
        if any(part not in (".", "..") and
               (_is_reserved_name(part) or part != part.strip(" .") or ":" in part)
               for part in rest):
            raise ScanError("SCAN_INPUT_INVALID", "reserved name")
    if not os.path.isabs(raw):
        raise ScanError("SCAN_INPUT_RELATIVE", "absolute path required")
    path = os.path.abspath(raw)
    try:
        chain = [path]
        parent = os.path.dirname(path)
        while parent and parent != chain[-1]:
            chain.append(parent)
            parent = os.path.dirname(parent)
        for item in chain:
            info = os.lstat(item)
            if os.path.islink(item):
                raise ScanError("SCAN_INPUT_SYMLINK", "link in path")
            if info.st_file_attributes & 0x400 if hasattr(info, "st_file_attributes") else False:
                raise ScanError("SCAN_INPUT_SYMLINK", "reparse point")
    except OSError as exc:
        if isinstance(exc, ScanError):
            raise
        raise ScanError("SCAN_INPUT_UNREADABLE", str(exc)) from exc
    try:
        with open(path, "rb"):
            pass
    except IsADirectoryError as exc:
        raise ScanError("SCAN_INPUT_IS_DIRECTORY", "not a file") from exc
    except OSError as exc:
        # Windows raises PermissionError, not IsADirectoryError, for directories.
        if os.path.isdir(path):
            raise ScanError("SCAN_INPUT_IS_DIRECTORY", "not a file") from exc
        raise ScanError("SCAN_INPUT_UNREADABLE", str(exc)) from exc
    size = os.path.getsize(path)
    if size > MAX_INPUT_BYTES:
        raise ScanError("SCAN_INPUT_TOO_LARGE", f"{size} bytes")
    return path


def _snapshot(path: str) -> tuple[int, int, str]:
    """Return size, mtime_ns, and sha256 hex of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns, digest.hexdigest()


def resolve_engine() -> str | None:
    """Return the trusted engine path, or None when no usable engine exists.

    Only fixed installation locations are considered, newest platform first.
    PATH, the working directory, and caller-supplied directories are never
    searched. Returns None on non-Windows platforms.
    """
    if not _is_windows():
        return None
    candidates: list[str] = []
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    platform_root = os.path.join(program_data, "Microsoft", "Windows Defender", "Platform")
    try:
        versions = sorted(os.listdir(platform_root), reverse=True)
    except OSError:
        versions = []
    for version in versions:
        candidates.append(os.path.join(platform_root, version, _ENGINE_FILENAME))
    candidates.append(os.path.join(program_files, "Windows Defender", _ENGINE_FILENAME))
    for candidate in candidates:
        try:
            if os.path.basename(candidate).lower() != _ENGINE_FILENAME:
                continue
            if os.path.islink(candidate) or not os.path.isfile(candidate):
                continue
            return candidate
        except OSError:
            continue
    return None


def _bounded_lines(text: str) -> tuple[list[str], bool]:
    lines = [line[:MAX_EVIDENCE_LINE_CHARS] for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if len(lines) > MAX_EVIDENCE_LINES:
        return lines[:MAX_EVIDENCE_LINES], True
    return lines, False


def interpret(exit_code: int, stdout_text: str) -> tuple[str, dict]:
    """Map engine exit code plus output to (outcome, evidence).

    Pure function: every branch is pinned by tests and mutants. A threat
    marker always wins (safe direction); a clean outcome needs exit 0 AND
    the engine's own no-threat marker; everything else is FAILED.
    """
    lowered = stdout_text.lower()
    threat_lines, threat_cut = _bounded_lines(
        "\n".join(line for line in stdout_text.splitlines() if _THREAT_WORD.search(line)))
    hr_match = _HR_TOKEN.search(stdout_text)
    evidence: dict = {
        "exit_code": exit_code,
        "matched_lines": threat_lines,
        "matched_lines_truncated": threat_cut,
        "hresult": hr_match.group(0).lower() if hr_match else None,
        "clean_marker_present": _CLEAN_MARKER in lowered,
        "failure_marker_present": _FAILURE_MARKER in lowered,
    }
    if threat_lines:
        return DETECTED, evidence
    if _FAILURE_MARKER in lowered:
        return FAILED, evidence
    if exit_code == 0 and _CLEAN_MARKER in lowered:
        return NO_DETECTION_REPORTED, evidence
    return FAILED, evidence


def scan_file(path: str, *, engine_command: tuple[str, ...] | None = None,
               timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Scan one validated absolute file path. Returns the JSON report dict.

    engine_command overrides the resolved engine for tests only (a fixed
    argv prefix, still no shell); production callers leave it None. Raises
    ScanError only for input problems; engine-world problems become report
    outcomes.
    """
    if not (MIN_TIMEOUT_S <= timeout_s <= MAX_TIMEOUT_S):
        raise ScanError("SCAN_TIMEOUT_OUT_OF_RANGE", str(timeout_s))
    target = input_path(path)
    started = utc_now()
    try:
        before = _snapshot(target)
    except OSError:
        return _report(started, target, None, INPUT_CHANGED_OR_UNSCANNABLE,
                       {"reason": "input_unreadable_before_scan"}, None, timeout_s)
    engine_argv: list[str]
    engine_label = "unavailable"
    fixed_tail = [*SCAN_ARGV_TAIL, target, "-DisableRemediation"]
    if engine_command is not None:
        if not engine_command or any(not part for part in engine_command):
            raise ScanError("SCAN_ENGINE_INVALID", "empty engine command")
        engine_argv = [*engine_command, *fixed_tail]
        engine_label = "test-stub"
    else:
        resolved = resolve_engine()
        if resolved is None:
            return _report(started, target, None, UNAVAILABLE,
                           {"reason": "engine_missing_or_unsupported_platform"},
                           before, timeout_s)
        engine_argv = [resolved, *fixed_tail]
        engine_label = os.path.basename(os.path.dirname(resolved)) + "/" + os.path.basename(resolved)
    try:
        completed = subprocess.run(
            engine_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"")[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
        lines, cut = _bounded_lines(partial)
        return _report(started, target, engine_label, TIMED_OUT_UNKNOWN,
                       {"partial_lines": lines, "partial_truncated": cut,
                        "note": "process wait expired; no retry issued"},
                       before, timeout_s)
    except OSError as exc:
        return _report(started, target, engine_label, UNAVAILABLE,
                       {"reason": f"engine_start_failed:{type(exc).__name__}"},
                       before, timeout_s)
    stdout_text = completed.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
    stdout_cut = len(completed.stdout) > MAX_OUTPUT_BYTES
    stderr_text = completed.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
    stderr_cut = len(completed.stderr) > MAX_OUTPUT_BYTES
    try:
        after = _snapshot(target)
    except OSError:
        after = None
    if after is None or after != before:
        return _report(started, target, engine_label, INPUT_CHANGED_OR_UNSCANNABLE,
                       {"before": _hash_only(before), "after": _hash_only(after)},
                       before, timeout_s, completed_at=True)
    outcome, evidence = interpret(completed.returncode, stdout_text)
    evidence["stdout_truncated"] = stdout_cut
    evidence["stderr_note"] = "captured" if stderr_text.strip() else "empty"
    if stderr_cut:
        evidence["stderr_note"] = "captured_truncated"
    return _report(started, target, engine_label, outcome, evidence, before,
                   timeout_s, completed_at=True)


def _hash_only(snapshot: tuple[int, int, str] | None) -> str | None:
    return snapshot[2] if snapshot else None


def _report(started: str, target: str, engine: str | None, outcome: str,
            evidence: dict, snapshot: tuple[int, int, str] | None,
            timeout_s: float, completed_at: bool = False) -> dict:
    return {
        "schema": SCAN_SCHEMA_VERSION,
        "started_at": started,
        "completed_at": utc_now() if completed_at else None,
        "input": {
            "name": os.path.basename(target),
            "size_bytes": snapshot[0] if snapshot else None,
            "sha256": _hash_only(snapshot),
        },
        "engine": {"label": engine or "unavailable"},
        "outcome": outcome,
        "evidence": evidence,
        "timeout_s": timeout_s,
        "cloud_boundary": _CLOUD_BOUNDARY,
    }


def format_report(report: dict) -> str:
    """Render one bounded human-readable summary. All values JSON-encoded."""
    line = (
        f"outcome={report['outcome']} "
        f"file={json.dumps(report['input']['name'], ensure_ascii=True)} "
        f"sha256={report['input']['sha256']} "
        f"engine={json.dumps(report['engine']['label'], ensure_ascii=True)}"
    )
    evidence = report.get("evidence", {})
    if report["outcome"] == DETECTED:
        for matched in evidence.get("matched_lines", [])[:MAX_EVIDENCE_LINES]:
            line += f"\n  detection: {json.dumps(matched, ensure_ascii=True)}"
    elif report["outcome"] == NO_DETECTION_REPORTED:
        line += "\n  no detection reported (not a guarantee of safety)"
    else:
        detail = json.dumps(evidence, ensure_ascii=True, sort_keys=True)[:600]
        line += f"\n  detail: {detail}"
    return line
