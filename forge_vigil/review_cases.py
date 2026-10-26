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
from pathlib import Path

from .evaluation import MAX_CASE_ID_CHARS, load_case_set
from .schema import RequestValidationError, input_digest, parse_request
from .store import Store
from .versions import CODE_VERSION

DEFAULT_CASES_PATH = Path("var/review_cases.json")
CASE_SET_VERSION = "local.reviews.v1"
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
        if input_digest(actor_id, request) == receipt["input_digest"]:
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

    cases_path = Path(cases_path)
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
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(partial, cases_path)
    return case
