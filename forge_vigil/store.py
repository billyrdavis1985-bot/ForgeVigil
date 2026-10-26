"""SQLite persistence for request intents, receipts and the local outbox.

Invariants, enforced here and by schema constraints and triggers:
* an intent row is committed (synchronous=FULL) before any assessment or
  delivery work starts;
* request completion, outbox insertion and receipt insertion happen in ONE
  transaction, guarded by the attempt that claimed the request;
* at most one receipt and one outbox item exist per (actor_id, request_id);
* receipts and outbox items are append-only; completed requests are final.

One active service instance per database file is assumed.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .versions import STORE_SCHEMA_VERSION

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS requests (
        actor_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        input_digest TEXT NOT NULL,
        document_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        approval_ref TEXT,
        adapter_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('in_progress', 'completed')),
        received_at TEXT NOT NULL,
        completed_at TEXT,
        PRIMARY KEY (actor_id, request_id)
    )""",
    """CREATE TABLE IF NOT EXISTS receipts (
        receipt_id TEXT PRIMARY KEY,
        actor_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        disposition TEXT NOT NULL CHECK (disposition IN ('ALLOW', 'BLOCK', 'DENY', 'REVIEW')),
        receipt_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (actor_id, request_id),
        FOREIGN KEY (actor_id, request_id) REFERENCES requests (actor_id, request_id)
    )""",
    """CREATE TABLE IF NOT EXISTS outbox (
        effect_id TEXT PRIMARY KEY,
        actor_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        recipient_address TEXT NOT NULL,
        body BLOB NOT NULL,
        body_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (actor_id, request_id),
        FOREIGN KEY (actor_id, request_id) REFERENCES requests (actor_id, request_id)
    )""",
    """CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
       BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
       BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS outbox_no_update BEFORE UPDATE ON outbox
       BEGIN SELECT RAISE(ABORT, 'outbox items are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS outbox_no_delete BEFORE DELETE ON outbox
       BEGIN SELECT RAISE(ABORT, 'outbox items are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS requests_completed_final BEFORE UPDATE ON requests
       WHEN OLD.state = 'completed'
       BEGIN SELECT RAISE(ABORT, 'completed requests are final'); END""",
    """CREATE TRIGGER IF NOT EXISTS requests_no_delete BEFORE DELETE ON requests
       BEGIN SELECT RAISE(ABORT, 'requests are retained'); END""",
)


class AttemptNotCurrent(Exception):
    """The claimed attempt no longer owns the request; nothing was written."""


@dataclass(frozen=True)
class Claim:
    """A durable intent: this attempt owns (actor_id, request_id)."""

    actor_id: str
    request_id: str
    input_digest: str
    document_id: str
    recipient_id: str
    approval_ref: str | None
    adapter_id: str
    attempt_id: str
    received_at: str


@dataclass(frozen=True)
class ExistingRequest:
    state: str
    input_digest: str
    receipt: dict | None


@dataclass(frozen=True)
class OutboxItem:
    effect_id: str
    actor_id: str
    request_id: str
    document_id: str
    recipient_id: str
    recipient_address: str
    body: bytes
    body_sha256: str
    created_at: str


_OUTBOX_COLUMNS = (
    "effect_id, actor_id, request_id, document_id, recipient_id, recipient_address, body, body_sha256, created_at"
)
_CLAIM_COLUMNS = (
    "actor_id, request_id, input_digest, document_id, recipient_id, approval_ref, adapter_id, attempt_id, received_at"
)


class Store:
    def __init__(self, path: str | Path, observer: Callable[[str], None] | None = None) -> None:
        self.path = Path(path)
        self._observer = observer
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA synchronous = FULL")
        except BaseException:
            conn.close()
            raise
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise
        finally:
            conn.close()

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _notify(self, event: str) -> None:
        if self._observer is not None:
            self._observer(event)

    def _initialize(self) -> None:
        with self._reader() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
        with self._transaction() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('store_schema', ?)", (STORE_SCHEMA_VERSION,)
            )
            (version,) = conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()
        if version != STORE_SCHEMA_VERSION:
            raise RuntimeError(f"unsupported store schema {version!r}; refusing to migrate implicitly")

    def claim(
        self,
        *,
        actor_id: str,
        request_id: str,
        input_digest: str,
        document_id: str,
        recipient_id: str,
        approval_ref: str | None,
        adapter_id: str,
        received_at: str,
    ) -> Claim | ExistingRequest:
        """Durably record intent, or report the request that already holds this key."""
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state, input_digest FROM requests WHERE actor_id = ? AND request_id = ?",
                (actor_id, request_id),
            ).fetchone()
            if row is not None:
                receipt = conn.execute(
                    "SELECT receipt_json FROM receipts WHERE actor_id = ? AND request_id = ?",
                    (actor_id, request_id),
                ).fetchone()
                return ExistingRequest(
                    state=row[0], input_digest=row[1], receipt=json.loads(receipt[0]) if receipt else None
                )
            claim = Claim(
                actor_id=actor_id,
                request_id=request_id,
                input_digest=input_digest,
                document_id=document_id,
                recipient_id=recipient_id,
                approval_ref=approval_ref,
                adapter_id=adapter_id,
                attempt_id=uuid.uuid4().hex,
                received_at=received_at,
            )
            conn.execute(
                f"INSERT INTO requests ({_CLAIM_COLUMNS}, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'in_progress')",
                (
                    claim.actor_id,
                    claim.request_id,
                    claim.input_digest,
                    claim.document_id,
                    claim.recipient_id,
                    claim.approval_ref,
                    claim.adapter_id,
                    claim.attempt_id,
                    claim.received_at,
                ),
            )
        self._notify("intent_committed")
        return claim

    def complete(self, claim: Claim, receipt: dict, outbox: OutboxItem | None) -> None:
        """Atomically finish a claimed request: state + optional outbox item + receipt."""
        if (outbox is not None) != (receipt["disposition"] == "ALLOW"):
            raise ValueError("an outbox item requires an ALLOW receipt, and ALLOW requires an outbox item")
        if outbox is not None and receipt["effect_id"] != outbox.effect_id:
            raise ValueError("receipt effect_id does not match the outbox item")
        receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        with self._transaction() as conn:
            updated = conn.execute(
                "UPDATE requests SET state = 'completed', completed_at = ? "
                "WHERE actor_id = ? AND request_id = ? AND attempt_id = ? AND state = 'in_progress'",
                (receipt["completed_at"], claim.actor_id, claim.request_id, claim.attempt_id),
            ).rowcount
            if updated != 1:
                raise AttemptNotCurrent
            if outbox is not None:
                conn.execute(
                    f"INSERT INTO outbox ({_OUTBOX_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        outbox.effect_id,
                        outbox.actor_id,
                        outbox.request_id,
                        outbox.document_id,
                        outbox.recipient_id,
                        outbox.recipient_address,
                        outbox.body,
                        outbox.body_sha256,
                        outbox.created_at,
                    ),
                )
                self._notify("outbox_inserted")
            conn.execute(
                "INSERT INTO receipts (receipt_id, actor_id, request_id, disposition, receipt_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    receipt["receipt_id"],
                    claim.actor_id,
                    claim.request_id,
                    receipt["disposition"],
                    receipt_json,
                    receipt["completed_at"],
                ),
            )
        self._notify("completion_committed")

    def get_receipt(self, actor_id: str, request_id: str) -> dict | None:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT receipt_json FROM receipts WHERE actor_id = ? AND request_id = ?", (actor_id, request_id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def incomplete_requests(self) -> list[Claim]:
        with self._reader() as conn:
            rows = conn.execute(
                f"SELECT {_CLAIM_COLUMNS} FROM requests WHERE state = 'in_progress' ORDER BY received_at"
            ).fetchall()
        return [Claim(*row) for row in rows]

    def outbox_items(self) -> list[OutboxItem]:
        with self._reader() as conn:
            rows = conn.execute(f"SELECT {_OUTBOX_COLUMNS} FROM outbox ORDER BY created_at, effect_id").fetchall()
        return [OutboxItem(*row) for row in rows]

    def table_counts(self) -> dict[str, int]:
        with self._reader() as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("requests", "receipts", "outbox")
            }

    def healthy(self) -> bool:
        try:
            with self._reader() as conn:
                conn.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
        except sqlite3.Error:
            return False
        return True
