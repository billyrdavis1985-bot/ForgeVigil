"""Request fingerprints: the digest stored in place of the request text.

Receipts and the requests table keep a digest of each request, never its
message. Up to 0.9.0 that digest was a plain SHA-256 of the normalized request
(`sha256:...`). Anyone with a copy of the database could confirm a guessed short
message by hashing it the same way. From 0.10.0 new digests are keyed
(`hmac-sha256:...`) with a secret kept beside the database in `<db>.key`, so the
database alone confirms nothing.

Old digests stay valid: a stored digest names its scheme, and comparisons use
that scheme, in constant time. If the key file is missing while the database
already holds keyed digests, nothing is created: a new key would turn every
replay of an earlier request into a conflict, so startup refuses instead.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from .schema import SubmittedRequest
from .versions import REQUEST_SCHEMA_VERSION

LEGACY_PREFIX = "sha256:"
KEYED_PREFIX = "hmac-sha256:"
KEY_BYTES = 32


class DigestKeyError(Exception):
    """The digest key is missing, unreadable or malformed; nothing was changed."""


def canonical_request(actor_id: str, request: SubmittedRequest) -> bytes:
    """The normalized payload: key order, JSON whitespace and absent-versus-null approval_ref do not matter."""
    normalized = {
        "schema": REQUEST_SCHEMA_VERSION,
        "actor_id": actor_id,
        "request_id": request.request_id,
        "document_id": request.document_id,
        "recipient_id": request.recipient_id,
        "approval_ref": request.approval_ref,
        "message": request.message,
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def legacy_digest(actor_id: str, request: SubmittedRequest) -> str:
    """The unkeyed digest used up to 0.9.0. Kept only to recognize records written then."""
    return LEGACY_PREFIX + hashlib.sha256(canonical_request(actor_id, request)).hexdigest()


def keyed_digest(key: bytes, actor_id: str, request: SubmittedRequest) -> str:
    return KEYED_PREFIX + hmac.new(key, canonical_request(actor_id, request), hashlib.sha256).hexdigest()


def is_keyed(digest: str) -> bool:
    return digest.startswith(KEYED_PREFIX)


def digest_matches(stored: str, key: bytes | None, actor_id: str, request: SubmittedRequest) -> bool:
    """Whether `request` is the request `stored` was made from, using the scheme `stored` names.

    A keyed digest needs the key; without it this returns False rather than guessing."""
    if stored.startswith(KEYED_PREFIX):
        if key is None:
            return False
        candidate = keyed_digest(key, actor_id, request)
    elif stored.startswith(LEGACY_PREFIX):
        candidate = legacy_digest(actor_id, request)
    else:
        return False
    return hmac.compare_digest(candidate.encode("ascii"), stored.encode("ascii", "replace"))


def key_path_for(db_path: Path) -> Path:
    db_path = Path(db_path)
    return db_path.with_name(db_path.name + ".key")


def load_key(db_path: Path) -> bytes | None:
    """The key for this database, or None if its key file does not exist."""
    path = key_path_for(db_path)
    if path.is_symlink():
        raise DigestKeyError(f"the digest key {path} is a link; refusing to follow it")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DigestKeyError(f"cannot read the digest key {path} ({exc})") from None
    try:
        with os.fdopen(fd, "r", encoding="ascii") as handle:
            text = handle.read().strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise DigestKeyError(f"cannot read the digest key {path} ({exc})") from None
    try:
        key = bytes.fromhex(text)
    except ValueError:
        key = b""
    if len(key) != KEY_BYTES:
        raise DigestKeyError(f"the digest key {path} is malformed (expected {KEY_BYTES * 2} hex characters)")
    return key


def load_or_create_key(db_path: Path, *, has_keyed_digests: bool) -> bytes:
    """The key for this database, creating an owner-only key file the first time.

    Refuses to create one when the database already holds keyed digests, because
    those can only be matched with the key that made them."""
    key = load_key(db_path)
    if key is not None:
        return key
    path = key_path_for(db_path)
    if has_keyed_digests:
        raise DigestKeyError(
            f"the digest key {path} is missing, but this database has records fingerprinted with it; "
            "restore the key file (a new key would make every earlier request look changed)"
        )
    key = secrets.token_bytes(KEY_BYTES)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        return load_or_create_key(db_path, has_keyed_digests=has_keyed_digests)  # another process just made it
    except OSError as exc:
        raise DigestKeyError(f"cannot create the digest key {path} ({exc.strerror})") from None
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(key.hex() + "\n")
    return key
