"""Strict request schema for POST /v1/requests.

Exactly five fields exist. Actor identity comes from authentication, never
from JSON; permissions, policy and assessments are server-owned, so any extra
field (actor, policy, assessment, ...) is rejected rather than ignored.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .versions import REQUEST_SCHEMA_VERSION

MAX_BODY_BYTES = 16 * 1024
MAX_MESSAGE_CHARS = 2000
# Opaque identifiers only: no '/', '.', ':', '%' or whitespace, so a path or
# URL can never pass as an id.
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

_ID_FIELDS = ("request_id", "document_id", "recipient_id")
_REQUIRED_FIELDS = frozenset({*_ID_FIELDS, "message"})
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"approval_ref"}
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class RequestValidationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SubmittedRequest:
    request_id: str
    document_id: str
    recipient_id: str
    approval_ref: str | None
    message: str


class _DuplicateField(Exception):
    pass


def _object_without_duplicates(pairs: list) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise _DuplicateField
        obj[key] = value
    return obj


def _reject_constant(name: str):
    raise ValueError(f"non-standard JSON constant {name}")


def parse_request(body: bytes) -> SubmittedRequest:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise RequestValidationError("invalid_encoding", "body must be UTF-8 encoded JSON") from None
    try:
        data = json.loads(text, object_pairs_hook=_object_without_duplicates, parse_constant=_reject_constant)
    except _DuplicateField:
        raise RequestValidationError("duplicate_field", "a JSON field appears more than once") from None
    except (ValueError, RecursionError):
        raise RequestValidationError("malformed_json", "body is not valid JSON") from None

    if not isinstance(data, dict):
        raise RequestValidationError("invalid_type", "body must be a JSON object")
    if set(data) - _ALLOWED_FIELDS:
        raise RequestValidationError(
            "unknown_field", "only request_id, document_id, recipient_id, approval_ref and message are accepted"
        )
    missing = _REQUIRED_FIELDS - set(data)
    if missing:
        raise RequestValidationError("missing_field", "missing required field(s): " + ", ".join(sorted(missing)))

    for name in _ID_FIELDS:
        _require_id(name, data[name])
    approval_ref = data.get("approval_ref")
    if approval_ref is not None:
        _require_id("approval_ref", approval_ref)

    message = data["message"]
    if not isinstance(message, str):
        raise RequestValidationError("invalid_field", "message must be a string")
    if not 1 <= len(message) <= MAX_MESSAGE_CHARS:
        raise RequestValidationError("invalid_field", f"message must be 1-{MAX_MESSAGE_CHARS} characters")
    if _CONTROL_CHARS.search(message) or not _utf8_encodable(message):
        raise RequestValidationError("invalid_field", "message contains disallowed control or surrogate characters")

    return SubmittedRequest(
        request_id=data["request_id"],
        document_id=data["document_id"],
        recipient_id=data["recipient_id"],
        approval_ref=approval_ref,
        message=message,
    )


def _require_id(name: str, value: object) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise RequestValidationError("invalid_field", f"{name} must be an opaque id matching {ID_PATTERN.pattern}")


def _utf8_encodable(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:  # lone surrogates from \ud800-style escapes
        return False
    return True


def input_digest(actor_id: str, request: SubmittedRequest) -> str:
    """Digest of the normalized payload, stored instead of the raw message.

    Key order, JSON whitespace and an absent-versus-null approval_ref do not
    change it. It is an unkeyed SHA-256, so short messages remain guessable.
    """
    normalized = {
        "schema": REQUEST_SCHEMA_VERSION,
        "actor_id": actor_id,
        "request_id": request.request_id,
        "document_id": request.document_id,
        "recipient_id": request.recipient_id,
        "approval_ref": request.approval_ref,
        "message": request.message,
    }
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
