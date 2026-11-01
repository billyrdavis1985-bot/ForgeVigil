"""Turn operator decisions into labelled evaluation cases.

The database stores digests, never request text, so the operator supplies the
original message. It is accepted only if it reproduces the recorded input
digest exactly, so a case is always the request that was really reviewed.

The decision sets the label: false_positive and release mean benign, confirm
means attack. A rejection does not say which, so it needs an explicit label.
Cases are appended to a local file (git-ignored under var/) that `eval --cases`
runs. The database is opened read-only.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import time
from pathlib import Path

from .evaluation import MAX_CASE_ID_CHARS, load_case_set
from .digests import DigestKeyError, digest_matches, is_keyed, key_path_for, load_key
from .instance import InstanceLock, InstanceLockError
from .schema import RequestValidationError, parse_request
from .store import Store
from .versions import CODE_VERSION

DEFAULT_CASES_PATH = Path("var/review_cases.json")
CASE_SET_VERSION = "local.reviews.v1"
_EXPORT_LOCK_ATTEMPTS = 100
_EXPORT_LOCK_RETRY_S = 0.005
_LABEL_FROM_DECISION = {"false_positive": "benign", "release": "benign", "confirm": "attack"}
_ATTACK_EXPECT = ["BLOCK", "REVIEW"]


class ExportError(Exception):
    """Nothing was written."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def read_message_file(path: Path) -> str:
    """UTF-8 with or without a byte-order mark, or UTF-16 with one (what PowerShell 5.1's `>` writes)."""
    data = Path(path).read_bytes()
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def _message_candidates(text: str) -> list[str]:
    """The file as written, plus the forms an editor may have changed it to (CRLF, one trailing newline)."""
    candidates = []
    for base in (text, text.replace("\r\n", "\n")):
        for candidate in (base, base[:-2] if base.endswith("\r\n") else base[:-1] if base.endswith("\n") else base):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _case_id(request_id: str) -> str:
    if len(request_id) <= MAX_CASE_ID_CHARS:
        return request_id
    suffix = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:8]
    return f"{request_id[:MAX_CASE_ID_CHARS - 9]}-{suffix}"


def _append_case(cases_path: Path, case: dict) -> dict:
    """Read, append and atomically replace. Callers must hold the cases lock."""
    cases_path = Path(cases_path)
    if cases_path.is_symlink():
        raise ExportError("invalid_cases_file", "the case-set destination must not be a symbolic link")
    if cases_path.exists():
        try:
            load_case_set(cases_path)
            data = json.loads(cases_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExportError("invalid_cases_file", f"{cases_path} is not a readable case set: {exc}") from None
    else:
        data = {
            "version": CASE_SET_VERSION,
            "about": "Cases exported from operator decisions. Contains request text: keep it local.",
            "cases": [],
        }
    if any(entry["id"] == case["id"] for entry in data["cases"]):
        raise ExportError("already_exported", f"{cases_path} already has case {case['id']!r}")
    data["cases"].append(case)

    # Write a sibling file and swap it in, so an interruption never leaves a half-written case set.
    cases_path.parent.mkdir(parents=True, exist_ok=True)
    partial = cases_path.with_name(cases_path.name + ".partial")
    try:
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        raise ExportError("export_busy", f"{partial} already exists; it was not changed") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if cases_path.is_symlink():
            raise ExportError("invalid_cases_file", "the case-set destination became a symbolic link")
        os.replace(partial, cases_path)
    finally:
        partial.unlink(missing_ok=True)  # exclusive creation succeeded: only our temporary file is removed
    return case


def export_case(
    store: Store,
    *,
    actor_id: str,
    request_id: str,
    message_text: str,
    cases_path: Path = DEFAULT_CASES_PATH,
    label: str | None = None,
    exported_at: str,
) -> dict:
    """Append the decided request as an evaluation case and return it."""
    receipt = store.get_receipt(actor_id, request_id)
    if receipt is None:
        raise ExportError("not_found", f"no completed request {request_id!r}")
    review = store.get_review(actor_id, request_id)
    if review is None:
        raise ExportError("not_decided", "only a request with an operator decision can become a case; decide it first")
    decision = review["decision"]
    derived = _LABEL_FROM_DECISION.get(decision)
    if derived is None and label is None:
        raise ExportError("label_required", f"a {decision} decision does not say benign or attack; pass --label")
    if derived is not None and label is not None and label != derived:
        raise ExportError("label_conflict", f"a {decision} decision means {derived}, not {label}")
    label = label or derived

    key = None
    if is_keyed(receipt["input_digest"]):
        try:
            key = load_key(store.path)
        except DigestKeyError as exc:
            raise ExportError("digest_key_unreadable", str(exc)) from None
        if key is None:
            raise ExportError("digest_key_missing", f"this request was fingerprinted with {key_path_for(store.path)}, "
                                                    "which is missing, so its message cannot be checked")
    message = None
    for candidate in _message_candidates(message_text):
        payload = {
            "request_id": request_id,
            "document_id": receipt["document_id"],
            "recipient_id": receipt["recipient_id"],
            "approval_ref": receipt["approval_ref"],
            "message": candidate,
        }
        try:
            request = parse_request(json.dumps(payload).encode("utf-8"))
        except RequestValidationError:
            continue
        if digest_matches(receipt["input_digest"], key, actor_id, request):
            message = candidate
            break
    if message is None:
        raise ExportError("message_mismatch", "this text is not the message that was submitted (its digest differs)")

    if label == "attack":
        expect = _ATTACK_EXPECT
    else:  # what the deterministic policy gives a clean request with this approval
        expect = ["ALLOW"] if receipt["approval_check"] == "verified" else ["REVIEW"]
    case = {
        "id": _case_id(request_id),
        "label": label,
        "expect": expect,
        "request": {
            "document_id": receipt["document_id"],
            "recipient_id": receipt["recipient_id"],
            "approval_ref": receipt["approval_ref"],
            "message": message,
        },
        "source": {
            "request_id": request_id,
            "receipt_id": receipt["receipt_id"],
            "original_disposition": receipt["disposition"],
            "original_reason_code": receipt["reason_code"],
            "review_id": review["review_id"],
            "decision": decision,
            "exported_at": exported_at,
            "code_version": CODE_VERSION,
        },
    }

    if (receipt.get("authority") or {}).get("kind") == "registry":
        authority = receipt["authority"]
        case["source"]["registry"] = {"snapshot": authority["snapshot"], "generation": authority["generation"],
                                       "delivery_context": receipt.get("delivery_context")}

    # Fail fast with no side effects; the same check runs again under the lock.
    if Path(cases_path).is_symlink():
        raise ExportError("invalid_cases_file", "the case-set destination must not be a symbolic link")
    # Serialize whole read-modify-write cycles: without the lock, two callers
    # can read the same base and the second replace silently drops the first
    # case. A stale .partial from a crashed process still ends in export_busy.
    for _attempt in range(_EXPORT_LOCK_ATTEMPTS):
        try:
            with InstanceLock(cases_path):
                return _append_case(cases_path, case)
        except InstanceLockError:
            time.sleep(_EXPORT_LOCK_RETRY_S)
    raise ExportError("export_busy", f"another export to {cases_path} did not finish in time")


# How `export_all` reports each journaled request; codes from export_case map onto these groups.
EXPORT_GROUPS = (
    "exported",
    "pending",           # held, but no operator decision yet
    "final",             # ALLOW or DENY: there is no decision to label it with
    "label_required",    # rejected: export it alone with --label
    "already_exported",
    "not_found",         # journaled, but this database has no completed request with that id
    "message_mismatch",  # the journal's text does not reproduce the stored fingerprint
    "failed",            # anything else, such as a missing digest key
)


def export_all(
    store: Store,
    *,
    actor_id: str,
    journal: dict[str, dict],
    cases_path: Path = DEFAULT_CASES_PATH,
    exported_at: str,
) -> dict[str, list[str]]:
    """Export every decided request found in the requester's journal. Returns request ids by group.

    Each one goes through export_case, so its message must reproduce the stored fingerprint."""
    groups: dict[str, list[str]] = {name: [] for name in EXPORT_GROUPS}
    for request_id, entry in journal.items():
        try:
            export_case(store, actor_id=actor_id, request_id=request_id, message_text=entry["message"],
                        cases_path=cases_path, exported_at=exported_at)
        except ExportError as exc:
            if exc.code == "not_decided":
                receipt = store.get_receipt(actor_id, request_id)
                group = "final" if receipt and receipt["disposition"] in ("ALLOW", "DENY") else "pending"
            else:
                group = exc.code if exc.code in groups else "failed"
            groups[group].append(request_id)
        else:
            groups["exported"].append(request_id)
    return groups
