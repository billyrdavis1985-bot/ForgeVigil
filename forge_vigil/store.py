"""SQLite persistence for request intents, receipts and the local outbox.

Invariants, enforced here and by schema constraints and triggers:
* an intent row is committed (synchronous=FULL) before any assessment or
  delivery work starts;
* request completion, outbox insertion and receipt insertion happen in ONE
  transaction, guarded by the attempt that claimed the request;
* at most one receipt and one outbox item exist per (actor_id, request_id);
* receipts and outbox items are append-only; completed requests are final;
* every live model call is reserved against the spend cap before it is made,
  and resolved spend entries are final.

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
    # Store schema 2: spend ledger for live model calls (amounts in nano-USD).
    """CREATE TABLE IF NOT EXISTS spend_ledger (
        reservation_id TEXT PRIMARY KEY,
        actor_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        model TEXT NOT NULL,
        reserved_nanousd INTEGER NOT NULL CHECK (reserved_nanousd >= 0),
        actual_nanousd INTEGER CHECK (actual_nanousd >= 0),
        input_tokens INTEGER CHECK (input_tokens >= 0),
        output_tokens INTEGER CHECK (output_tokens >= 0),
        state TEXT NOT NULL CHECK (state IN ('reserved', 'settled', 'unknown')),
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (actor_id, request_id) REFERENCES requests (actor_id, request_id)
    )""",
    """CREATE TRIGGER IF NOT EXISTS spend_ledger_resolved_final BEFORE UPDATE ON spend_ledger
       WHEN OLD.state != 'reserved'
       BEGIN SELECT RAISE(ABORT, 'resolved spend entries are final'); END""",
    """CREATE TRIGGER IF NOT EXISTS spend_ledger_no_delete BEFORE DELETE ON spend_ledger
       BEGIN SELECT RAISE(ABORT, 'spend entries are retained'); END""",
    # Store schema 3: operator review decisions, at most one per request.
    """CREATE TABLE IF NOT EXISTS reviews (
        review_id TEXT PRIMARY KEY,
        actor_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        original_receipt_id TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('release', 'reject', 'confirm', 'false_positive')),
        reviewer TEXT NOT NULL,
        review_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (actor_id, request_id),
        FOREIGN KEY (actor_id, request_id) REFERENCES requests (actor_id, request_id),
        FOREIGN KEY (original_receipt_id) REFERENCES receipts (receipt_id)
    )""",
    """CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON reviews
       BEGIN SELECT RAISE(ABORT, 'review decisions are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON reviews
       BEGIN SELECT RAISE(ABORT, 'review decisions are append-only'); END""",
)
# Every upgrade so far only adds tables: 1 -> 2 the spend ledger, 2 -> 3 operator reviews.
_MIGRATABLE_VERSIONS = (None, "1", "2", STORE_SCHEMA_VERSION)
# Which operator decisions each held disposition accepts. Only REVIEW can ever be released.
REVIEW_DECISIONS = {"REVIEW": ("release", "reject"), "BLOCK": ("confirm", "false_positive")}


class AttemptNotCurrent(Exception):
    """The claimed attempt no longer owns the request; nothing was written."""


class ReviewRefused(Exception):
    """A review decision conflicts with recorded state; nothing was written."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


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
    review: dict | None = None


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


@dataclass(frozen=True)
class Snapshot:
    receipts: list[dict]
    reviews: list[dict]
    delivery_keys: list[tuple[str, str]]  # (actor_id, request_id) per outbox item
    spend_entries: list[dict]
    committed_spend_nanousd: int


_OUTBOX_COLUMNS = (
    "effect_id, actor_id, request_id, document_id, recipient_id, recipient_address, body, body_sha256, created_at"
)
_CLAIM_COLUMNS = (
    "actor_id, request_id, input_digest, document_id, recipient_id, approval_ref, adapter_id, attempt_id, received_at"
)


class Store:
    def __init__(
        self, path: str | Path, observer: Callable[[str], None] | None = None, *, read_only: bool = False
    ) -> None:
        """`read_only` opens an existing current-schema database that SQLite itself will refuse to write."""
        self.path = Path(path)
        self._observer = observer
        self._read_only = read_only
        if read_only:
            self._check_current_schema()
        else:
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._read_only:
            uri = self.path.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        else:
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
            conn.execute(_SCHEMA[0])
            row = conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()
            version = row[0] if row else None
            if version not in _MIGRATABLE_VERSIONS:
                # Raised inside the transaction, so nothing is written to an unknown store.
                raise RuntimeError(f"unsupported store schema {version!r}; refusing to migrate implicitly")
            for statement in _SCHEMA[1:]:
                conn.execute(statement)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('store_schema', ?)", (STORE_SCHEMA_VERSION,)
            )

    def _check_current_schema(self) -> None:
        # A read-only store never migrates, so an older or unknown schema is refused.
        with self._reader() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()
        version = row[0] if row else None
        if version != STORE_SCHEMA_VERSION:
            raise RuntimeError(
                f"store schema is {version!r}, not {STORE_SCHEMA_VERSION!r}; run serve or review once to upgrade it"
            )

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
                review = conn.execute(
                    "SELECT review_json FROM reviews WHERE actor_id = ? AND request_id = ?",
                    (actor_id, request_id),
                ).fetchone()
                return ExistingRequest(
                    state=row[0],
                    input_digest=row[1],
                    receipt=json.loads(receipt[0]) if receipt else None,
                    review=json.loads(review[0]) if review else None,
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

    def record_review(self, review: dict, outbox: OutboxItem | None) -> None:
        """Atomically record an operator decision and, for a release, its single outbox item.

        The checks are repeated here, inside the transaction, so a race or a
        caller bug cannot release anything but an undecided REVIEW receipt.
        """
        releasing = review["decision"] == "release"
        if (outbox is not None) != releasing:
            raise ValueError("an outbox item requires a release decision, and a release requires one")
        if outbox is not None and review["effect_id"] != outbox.effect_id:
            raise ValueError("review effect_id does not match the outbox item")
        review_json = json.dumps(review, sort_keys=True, separators=(",", ":"))
        key = (review["actor_id"], review["request_id"])
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT receipt_id, disposition FROM receipts WHERE actor_id = ? AND request_id = ?", key
            ).fetchone()
            if row is None or row[0] != review["original_receipt_id"]:
                raise ReviewRefused("not_found", "no matching receipt for this request")
            if review["decision"] not in REVIEW_DECISIONS.get(row[1], ()):
                raise ReviewRefused("decision_not_allowed", f"{review['decision']} is not allowed for a {row[1]} receipt")
            if conn.execute("SELECT 1 FROM reviews WHERE actor_id = ? AND request_id = ?", key).fetchone():
                raise ReviewRefused("already_decided", "this request already has a review decision")
            if outbox is not None:
                # The UNIQUE (actor_id, request_id) constraint still caps every request at one delivery.
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
                self._notify("release_outbox_inserted")
            conn.execute(
                "INSERT INTO reviews (review_id, actor_id, request_id, original_receipt_id, decision, reviewer, "
                "review_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review["review_id"],
                    review["actor_id"],
                    review["request_id"],
                    review["original_receipt_id"],
                    review["decision"],
                    review["reviewer"],
                    review_json,
                    review["decided_at"],
                ),
            )
        self._notify("review_committed")

    def snapshot(self) -> Snapshot:
        """Everything the operator report needs, read in ONE transaction so the parts agree
        even while serve keeps writing. Outbox bodies are not read."""
        with self._reader() as conn:
            conn.execute("BEGIN")
            try:
                receipts = conn.execute("SELECT receipt_json FROM receipts ORDER BY created_at, receipt_id").fetchall()
                reviews = conn.execute("SELECT review_json FROM reviews ORDER BY created_at, review_id").fetchall()
                deliveries = conn.execute("SELECT actor_id, request_id FROM outbox ORDER BY created_at").fetchall()
                cursor = conn.cursor()
                cursor.row_factory = sqlite3.Row
                spend = cursor.execute("SELECT * FROM spend_ledger ORDER BY created_at, reservation_id").fetchall()
                committed = _committed_spend(conn)
            finally:
                conn.execute("ROLLBACK")
        return Snapshot(
            receipts=[json.loads(row[0]) for row in receipts],
            reviews=[json.loads(row[0]) for row in reviews],
            delivery_keys=[(row[0], row[1]) for row in deliveries],
            spend_entries=[dict(row) for row in spend],
            committed_spend_nanousd=committed,
        )

    def review_queue(self) -> list[tuple[dict, dict | None]]:
        """REVIEW and BLOCK receipts, oldest first, each paired with its decision if one exists."""
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT r.receipt_json, v.review_json FROM receipts r LEFT JOIN reviews v "
                "ON v.actor_id = r.actor_id AND v.request_id = r.request_id "
                "WHERE r.disposition IN ('REVIEW', 'BLOCK') ORDER BY r.created_at, r.receipt_id"
            ).fetchall()
        return [(json.loads(receipt), json.loads(review) if review else None) for receipt, review in rows]

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

    def reserve_spend(
        self,
        *,
        actor_id: str,
        request_id: str,
        attempt_id: str,
        model: str,
        amount_nanousd: int,
        cap_nanousd: int,
        created_at: str,
    ) -> str | None:
        """Atomically reserve a call's worst-case cost, or return None if it would exceed the cap."""
        with self._transaction() as conn:
            if _committed_spend(conn) + amount_nanousd > cap_nanousd:
                return None
            reservation_id = "sp_" + uuid.uuid4().hex
            conn.execute(
                "INSERT INTO spend_ledger (reservation_id, actor_id, request_id, attempt_id, model, "
                "reserved_nanousd, state, created_at) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?)",
                (reservation_id, actor_id, request_id, attempt_id, model, amount_nanousd, created_at),
            )
        return reservation_id

    def settle_spend(
        self, reservation_id: str, *, actual_nanousd: int, input_tokens: int, output_tokens: int, resolved_at: str
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                "UPDATE spend_ledger SET state = 'settled', actual_nanousd = ?, input_tokens = ?, output_tokens = ?, "
                "resolved_at = ? WHERE reservation_id = ? AND state = 'reserved'",
                (actual_nanousd, input_tokens, output_tokens, resolved_at, reservation_id),
            )

    def mark_spend_unknown(self, reservation_id: str, *, resolved_at: str) -> None:
        """Usage could not be confirmed: the full reservation stays counted against the cap."""
        with self._transaction() as conn:
            conn.execute(
                "UPDATE spend_ledger SET state = 'unknown', resolved_at = ? WHERE reservation_id = ? AND state = 'reserved'",
                (resolved_at, reservation_id),
            )

    def recover_spend(self, resolved_at: str) -> int:
        """Reservations left in flight by a previous process become 'unknown' (still counted)."""
        with self._transaction() as conn:
            return conn.execute(
                "UPDATE spend_ledger SET state = 'unknown', resolved_at = ? WHERE state = 'reserved'", (resolved_at,)
            ).rowcount

    def committed_spend_nanousd(self) -> int:
        with self._reader() as conn:
            return _committed_spend(conn)

    def spend_entries(self) -> list[dict]:
        with self._reader() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM spend_ledger ORDER BY created_at, reservation_id")]


def _committed_spend(conn: sqlite3.Connection) -> int:
    # Settled calls count what they cost; in-flight and unknown calls count their full reservation.
    (total,) = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN state = 'settled' THEN actual_nanousd ELSE reserved_nanousd END), 0) "
        "FROM spend_ledger"
    ).fetchone()
    return int(total)
