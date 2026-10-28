"""Operator-owned registry snapshots and purpose-separated delivery bindings.

No request or model selects these facts. This module performs no network I/O;
documents are inline, never paths. Complete snapshots contain private bytes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .fixtures import Actor, Approval, Document, FixtureSet, Recipient
from .schema import ID_PATTERN

REGISTRY_FORMAT = "forgevigil.registry.v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


class RegistryError(ValueError):
    def __init__(self, code: str, field: str = "registry") -> None:
        # Field paths are constructed by code; never interpolate rejected input.
        self.code, self.field = code, field
        super().__init__(f"{code}: {field}")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _object(value, fields: set[str], field: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise RegistryError("invalid_fields", field)


def _text(value, field: str, limit: int) -> None:
    if type(value) is not str or not 1 <= len(value) <= limit or _CONTROL.search(value):
        raise RegistryError("invalid_text", field)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise RegistryError("invalid_text", field) from None


def _id(value, field: str) -> None:
    if type(value) is not str or not ID_PATTERN.fullmatch(value):
        raise RegistryError("invalid_id", field)


def _hash(value, field: str) -> None:
    if type(value) is not str or not _HASH.fullmatch(value):
        raise RegistryError("invalid_hash", field)


def _boolean(value, field: str) -> None:
    if type(value) is not bool:
        raise RegistryError("invalid_boolean", field)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RegistryError("duplicate_key")
        value[key] = item
    return value


def _nonfinite(_):
    raise RegistryError("invalid_json")


@dataclass(frozen=True)
class Registry:
    canonical_json: str

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def data(self) -> dict:
        # Return a fresh value; callers cannot mutate a validated snapshot.
        return json.loads(self.canonical_json)

    def fixtures(self) -> FixtureSet:
        data = self.data
        return FixtureSet.build(
            version="registry.v1:" + self.digest,
            actors=[Actor(x["id"], x["active"], x["may_send_documents"]) for x in data["actors"]],
            documents=[Document(x["id"], x["title"], x["classification"], base64.b64decode(x["content_base64"]))
                       for x in data["documents"] if x["status"] == "active"],
            recipients=[Recipient(x["id"], x["address"], x["approved"]) for x in data["recipients"]],
            approvals=[Approval(x["ref"], x["actor_id"], x["document_id"], x["recipient_id"], x["status"])
                       for x in data["approvals"]],
        )


def parse_registry(raw: bytes) -> Registry:
    if len(raw) > MAX_FILE_BYTES:
        raise RegistryError("file_too_large")
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
        return registry_from_value(data)
    except RegistryError:
        raise
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise RegistryError("invalid_json") from None


def registry_from_value(data: object) -> Registry:
    _object(data, {"format", "registry_id", "actors", "documents", "recipients", "approvals"}, "registry")
    if data["format"] != REGISTRY_FORMAT:
        raise RegistryError("unknown_format")
    _id(data["registry_id"], "registry_id")
    tables = {}
    for name, key, low, high in (("actors", "id", 1, 1), ("documents", "id", 1, 64),
                                 ("recipients", "id", 1, 256), ("approvals", "ref", 0, 1024)):
        values = data[name]
        if type(values) is not list or not low <= len(values) <= high:
            raise RegistryError("invalid_count", name)
        tables[name] = {}
        for i, item in enumerate(values):
            if type(item) is not dict or key not in item:
                raise RegistryError("invalid_fields", f"{name}[{i}]")
            _id(item[key], f"{name}[{i}].{key}")
            if item[key] in tables[name]:
                raise RegistryError("duplicate_id", name)
            tables[name][item[key]] = item
    actor = data["actors"][0]
    _object(actor, {"id", "active", "may_send_documents"}, "actors[0]")
    if actor["id"] != "operator":
        raise RegistryError("invalid_actor", "actors[0].id")
    for field in ("active", "may_send_documents"):
        _boolean(actor[field], "actors[0]." + field)
    total = 0
    for i, doc in enumerate(data["documents"]):
        field = f"documents[{i}]"
        _object(doc, {"id", "version", "title", "status", "classification", "sha256", "content_base64"}, field)
        _id(doc["version"], field + ".version")
        _text(doc["title"], field + ".title", 200)
        if doc["status"] not in ("active", "withdrawn") or doc["classification"] not in ("approved_public", "restricted"):
            raise RegistryError("invalid_enum", field)
        _hash(doc["sha256"], field + ".sha256")
        encoded = doc["content_base64"]
        if type(encoded) is not str or len(encoded) > 1398104:
            raise RegistryError("invalid_content", field)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError):
            raise RegistryError("invalid_content", field) from None
        if not 0 < len(content) <= MAX_DOCUMENT_BYTES or base64.b64encode(content).decode("ascii") != encoded:
            raise RegistryError("invalid_content", field)
        if hashlib.sha256(content).hexdigest() != doc["sha256"]:
            raise RegistryError("content_hash_mismatch", field)
        total += len(content)
    if total > MAX_TOTAL_BYTES:
        raise RegistryError("total_content_too_large", "documents")
    for i, recipient in enumerate(data["recipients"]):
        field = f"recipients[{i}]"
        _object(recipient, {"id", "version", "name", "address", "approved"}, field)
        _id(recipient["version"], field + ".version")
        _text(recipient["name"], field + ".name", 120)
        _boolean(recipient["approved"], field + ".approved")
        address = recipient["address"]
        if type(address) is not str or not 3 <= len(address) <= 254 or address.count("@") != 1 \
                or any(not 33 <= ord(c) <= 126 for c in address):
            raise RegistryError("invalid_address", field + ".address")
        local, domain = address.split("@")
        if not local or any(not _DOMAIN_LABEL.fullmatch(part) for part in domain.split(".")):
            raise RegistryError("invalid_address", field + ".address")
    for i, approval in enumerate(data["approvals"]):
        field = f"approvals[{i}]"
        _object(approval, {"ref", "actor_id", "document_id", "document_version", "document_sha256",
                           "recipient_id", "recipient_version", "recipient_address_sha256", "status"}, field)
        for name in ("actor_id", "document_id", "document_version", "recipient_id", "recipient_version"):
            _id(approval[name], field + "." + name)
        for name in ("document_sha256", "recipient_address_sha256"):
            _hash(approval[name], field + "." + name)
        if approval["status"] not in ("active", "revoked"):
            raise RegistryError("invalid_enum", field + ".status")
        doc = tables["documents"].get(approval["document_id"])
        recipient = tables["recipients"].get(approval["recipient_id"])
        if approval["actor_id"] not in tables["actors"] or doc is None or recipient is None:
            raise RegistryError("unknown_reference", field)
        if (approval["document_version"], approval["document_sha256"]) != (doc["version"], doc["sha256"]):
            raise RegistryError("approval_document_mismatch", field)
        address_hash = hashlib.sha256(recipient["address"].encode("ascii")).hexdigest()
        if (approval["recipient_version"], approval["recipient_address_sha256"]) != (recipient["version"], address_hash):
            raise RegistryError("approval_recipient_mismatch", field)
    normalized = dict(data)
    for name, key in (("actors", "id"), ("documents", "id"), ("recipients", "id"), ("approvals", "ref")):
        normalized[name] = sorted(data[name], key=lambda x: x[key])
    return Registry(canonical(normalized))


def load_registry(path: Path) -> Registry:
    """Read one bounded regular private file; refuse symlinks, never repair permissions."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        before = Path(path).lstat()
        if stat.S_ISLNK(before.st_mode):
            raise RegistryError("unsafe_file")
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
                raise RegistryError("unsafe_file")
            if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise RegistryError("unsafe_permissions")
            if info.st_size > MAX_FILE_BYTES:
                raise RegistryError("file_too_large")
            return parse_registry(handle.read(MAX_FILE_BYTES + 1))
    except RegistryError:
        raise
    except OSError:
        raise RegistryError("unreadable_file") from None


def check_successor(previous: Registry, candidate: Registry) -> None:
    old, new = previous.data, candidate.data
    if old["registry_id"] != new["registry_id"]:
        raise RegistryError("registry_id_changed")
    for name, key, bound in (
        ("documents", "id", ("version", "sha256", "content_base64")),
        ("recipients", "id", ("version", "address")),
        ("approvals", "ref", ("actor_id", "document_id", "document_version", "document_sha256",
                               "recipient_id", "recipient_version", "recipient_address_sha256")),
    ):
        items = {x[key]: x for x in new[name]}
        for item in old[name]:
            current = items.get(item[key])
            if current is None:
                raise RegistryError("identity_removed", name)
            if any(item[field] != current[field] for field in bound):
                raise RegistryError("identity_changed", name)
            if name == "approvals" and item["status"] == "revoked" and current["status"] != "revoked":
                raise RegistryError("approval_resurrected", name)


def authority_identity(registry: Registry | None, generation: int | None) -> dict:
    return {"kind": "registry" if registry else "builtin", "snapshot": registry.digest if registry else None,
            "generation": generation}


def delivery_context(key: bytes, actor_id: str, document_id: str, recipient_id: str,
                     document_version: str, recipient_version: str, body: bytes, address: str) -> dict:
    body_hash = hashlib.sha256(body).hexdigest()
    material = [actor_id, document_id, document_version, body_hash, recipient_id, recipient_version, address]
    mac = hmac.new(key, b"forgevigil.delivery-context.v1\0" + canonical(material).encode("utf-8"), hashlib.sha256)
    return {"document_version": document_version, "document_sha256": body_hash,
            "recipient_version": recipient_version, "binding": "hmac-sha256:" + mac.hexdigest()}


def context_for(fixtures: FixtureSet, key: bytes, actor_id: str, document_id: str, recipient_id: str,
                registry: Registry | None = None) -> dict | None:
    doc, recipient = fixtures.documents.get(document_id), fixtures.recipients.get(recipient_id)
    if doc is None or recipient is None:
        return None
    dv = rv = fixtures.version
    if registry:
        data = registry.data
        dv = next(x["version"] for x in data["documents"] if x["id"] == document_id)
        rv = next(x["version"] for x in data["recipients"] if x["id"] == recipient_id)
    return delivery_context(key, actor_id, document_id, recipient_id, dv, rv, doc.content, recipient.address)


def same_context(first: dict | None, second: dict | None) -> bool:
    return first is not None and second is not None and hmac.compare_digest(
        canonical(first).encode("utf-8"), canonical(second).encode("utf-8"))


def export_snapshot(registry: Registry, path: Path) -> None:
    """Exclusive new-file publication, including late arrivals and symbolic links."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write((registry.canonical_json + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def activate_registry(path: Path, registry: Registry, reviewer: str = "operator") -> int:
    """Local operator entry point. Never callable over HTTP or by an assessor tool."""
    from .digests import load_or_create_key
    from .instance import InstanceLock, secure_state_files
    from .service import utc_now
    from .store import Store

    registry = parse_registry(registry.canonical_json.encode("utf-8"))
    _id(reviewer, "reviewer")
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = InstanceLock(path)
    lock.acquire()
    try:
        path = lock.db_path
        secure_state_files(path)
        store = Store(path)
        load_or_create_key(path, has_keyed_digests=store.has_keyed_digests())
        return store._activate_registry(registry, reviewer, utc_now())
    finally:
        secure_state_files(lock.db_path)
        lock.release()


def verify_database_authority(conn, key: bytes | None) -> int:
    """Check store-4 history and bindings on an already read-only snapshot.

    A checksum alone cannot detect a self-consistent but invalid registry history.
    No journal/message text is needed to prove a registry context's MAC.
    """
    from .fixtures import default_fixtures
    from .policy import policy_digest

    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RegistryError("broken_authority_reference")
    snapshots = {}
    for digest, fmt, registry_id, text in conn.execute(
            "SELECT digest, format, registry_id, canonical_json FROM registry_snapshots"):
        snapshot = parse_registry(text.encode("utf-8"))
        if snapshot.digest != digest or snapshot.canonical_json != text or fmt != REGISTRY_FORMAT or registry_id != snapshot.data["registry_id"]:
            raise RegistryError("corrupt_snapshot")
        snapshots[digest] = snapshot
    activations, used = {}, set()
    previous = None
    for generation, digest, reviewer in conn.execute(
            "SELECT generation, snapshot_digest, reviewer FROM registry_activations ORDER BY generation"):
        if generation != len(activations) + 1 or digest not in snapshots:
            raise RegistryError("broken_activation_history")
        _id(reviewer, "reviewer")
        snapshot = snapshots[digest]
        if previous:
            check_successor(previous, snapshot)
        previous = snapshot
        activations[generation] = digest
        used.add(digest)
    if used != set(snapshots):
        raise RegistryError("orphan_snapshot")
    if activations and conn.execute(
            "SELECT 1 FROM requests r LEFT JOIN request_authority a ON a.actor_id = r.actor_id AND a.request_id = r.request_id WHERE a.actor_id IS NULL LIMIT 1").fetchone():
        raise RegistryError("missing_request_authority")
    for actor, request_id, text in conn.execute("SELECT actor_id, request_id, receipt_json FROM receipts"):
        receipt = json.loads(text)
        if receipt.get("receipt_schema") == "forgevigil.receipt.v6":
            origin = conn.execute("SELECT 1 FROM request_authority WHERE actor_id = ? AND request_id = ?", (actor, request_id)).fetchone()
            kind = (receipt.get("authority") or {}).get("kind")
            if not origin and (kind != "legacy_unknown" or receipt.get("delivery_context") is not None or receipt.get("delivered")):
                raise RegistryError("missing_receipt_authority")
    confirmed = 0
    for actor, request_id, kind, digest, generation, saved_policy, fixture_version, context_json in conn.execute(
            "SELECT actor_id, request_id, kind, snapshot_digest, generation, policy_digest, fixture_version, context_json FROM request_authority"):
        request = conn.execute("SELECT document_id, recipient_id FROM requests WHERE actor_id = ? AND request_id = ?", (actor, request_id)).fetchone()
        if request is None:
            raise RegistryError("orphan_request_authority")
        if kind == "registry":
            if activations.get(generation) != digest:
                raise RegistryError("request_authority_mismatch")
            snapshot = snapshots[digest]
            fixtures = snapshot.fixtures()
        elif kind == "builtin" and digest is None and generation is None and not activations:
            snapshot, fixtures = None, default_fixtures()
        else:
            raise RegistryError("request_authority_mismatch")
        if saved_policy != policy_digest(fixtures) or fixture_version != fixtures.version:
            raise RegistryError("request_policy_mismatch")
        context = json.loads(context_json) if context_json else None
        if context is None and request[0] in fixtures.documents and request[1] in fixtures.recipients:
            raise RegistryError("missing_delivery_context")
        if context is not None:
            if key is None:
                raise RegistryError("context_key_missing")
            if not same_context(context, context_for(fixtures, key, actor, *request, snapshot)):
                raise RegistryError("context_mac_mismatch")
            confirmed += 1
        receipt_row = conn.execute("SELECT receipt_json FROM receipts WHERE actor_id = ? AND request_id = ?", (actor, request_id)).fetchone()
        if receipt_row:
            receipt = json.loads(receipt_row[0])
            if receipt.get("authority") != {"kind": kind, "snapshot": digest, "generation": generation} or receipt.get("delivery_context") != context or receipt.get("policy_digest") != saved_policy:
                raise RegistryError("receipt_authority_mismatch")
        for document_id, recipient_id, address, body, body_hash in conn.execute(
                "SELECT document_id, recipient_id, recipient_address, body, body_sha256 FROM outbox WHERE actor_id = ? AND request_id = ?", (actor, request_id)):
            if key is None or context is None or (document_id, recipient_id) != request:
                raise RegistryError("outbox_context_mismatch")
            actual = delivery_context(key, actor, document_id, recipient_id, context["document_version"], context["recipient_version"], body, address)
            if not same_context(context, actual) or hashlib.sha256(body).hexdigest() != body_hash:
                raise RegistryError("outbox_context_mismatch")
    return confirmed
