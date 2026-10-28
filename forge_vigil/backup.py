"""Backups of the operator's state: the database, its digest key and the requester's journal.

`backup create` snapshots the database with SQLite's online backup, which reads one
consistent state even while `serve` keeps writing, and copies the key and the journal
byte for byte. A manifest records each file's SHA-256 and the database's row counts.
The backup is built in a hidden `.partial` folder, verified, and only then renamed, so
a backup folder exists complete and verified or not at all.

`backup verify` checks a backup without writing to it:
- every file's size and hash;
- SQLite's integrity check;
- the store schema and row counts;
- that the key really belongs to the database, by recomputing the fingerprints of
  journaled requests. A key that cannot be confirmed this way is reported.

`backup restore` verifies first and never overwrites anything. It holds the same lock
`serve` takes, and places the database last, so an interrupted restore never looks
complete.

A backup holds the key and the journal's message text, so it is as sensitive as the
live state: owner-only on POSIX, and to be kept off shared storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .client import read_journal
from .digests import DigestKeyError, digest_matches, is_keyed, key_path_for, load_key
from .instance import InstanceLock, InstanceLockError, lock_path_for, secure_state_files
from .schema import RequestValidationError, parse_request
from .versions import BACKUP_SCHEMA_VERSION, CODE_VERSION, STORE_SCHEMA_VERSION

DEFAULT_BACKUP_ROOT = Path("var/backups")
MANIFEST_NAME = "manifest.json"
COUNTED_TABLES = ("requests", "receipts", "outbox", "reviews", "spend_ledger",
                  "registry_snapshots", "registry_activations", "request_authority")
_OLDER_STORE_SCHEMAS = ("1", "2", "3")  # `serve` upgrades these after a restore


class BackupError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class Verification:
    folder: Path
    manifest: dict | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()  # Windows requires the handle closed before cleanup
            path.unlink(missing_ok=True)  # exclusive creation succeeded; this call owns the file
            raise


def _rename(source: Path, target: Path) -> None:
    """os.replace, retried briefly: Windows can hold a just-written file open for a moment (a virus scanner)."""
    for _ in range(50):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(source, target)


def _snapshot_database(source: Path, target: Path) -> None:
    """One consistent copy of a live WAL database, as a single self-contained file."""
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10.0)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")  # no -wal or -shm beside the copy
        finally:
            dst.close()
    finally:
        src.close()
    if os.name == "posix":
        os.chmod(target, 0o600)


def database_facts(path: Path) -> dict:
    """Integrity, schema, row counts and digest kind of a database file nothing else is using.

    Opened immutable and read-only, so SQLite writes nothing next to it."""
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        row = conn.execute("SELECT value FROM meta WHERE key = 'store_schema'").fetchone()
        version = row[0] if row else None
        tables = COUNTED_TABLES if version == STORE_SCHEMA_VERSION else COUNTED_TABLES[:5]
        existing = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        allowed_missing = {"1": {"reviews", "spend_ledger"}, "2": {"reviews"}}.get(version, set())
        counts = {table: (0 if table not in existing and table in allowed_missing else
                         conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
        keyed = conn.execute(
            "SELECT 1 FROM requests WHERE input_digest LIKE 'hmac-sha256:%' LIMIT 1").fetchone() is not None
        receipts = [json.loads(text) for (text,) in conn.execute("SELECT receipt_json FROM receipts")]
    finally:
        conn.close()
    return {"integrity": integrity, "store_schema": row[0] if row else None, "counts": counts,
            "keyed_digests": keyed, "receipts": receipts}


def _plain_name(name: object) -> bool:
    """A manifest may only name files directly inside its own backup folder."""
    return isinstance(name, str) and name not in ("", ".", "..") and Path(name).name == name \
        and "/" not in name and "\\" not in name and not name.startswith(".")


def _check_key_against_journal(key: bytes, journal_path: Path, receipts: list[dict], result: Verification) -> None:
    """Recompute keyed fingerprints from journaled text. The only proof that a key belongs to its database."""
    entries, unreadable = read_journal(journal_path)
    if unreadable:
        result.notes.append(f"journal: {unreadable} line(s) could not be read")
    by_id: dict[str, list[dict]] = {}
    for receipt in receipts:
        by_id.setdefault(receipt["request_id"], []).append(receipt)
    confirmed, mismatched, newer = 0, [], 0
    for request_id, entry in entries.items():
        candidates = [r for r in by_id.get(request_id, []) if is_keyed(r["input_digest"])]
        if not candidates:
            newer += request_id not in by_id
            continue
        payload = {name: entry.get(name) for name in ("request_id", "document_id", "recipient_id", "approval_ref", "message")}
        try:
            request = parse_request(json.dumps(payload).encode("utf-8"))
        except RequestValidationError:
            mismatched.append(request_id)
            continue
        if any(digest_matches(r["input_digest"], key, r["actor_id"], request) for r in candidates):
            confirmed += 1
        else:
            mismatched.append(request_id)
    if mismatched:
        result.problems.append(
            f"key: the journaled text of {len(mismatched)} request(s) does not reproduce its stored fingerprint "
            f"with this key (wrong key, or altered journal): {', '.join(sorted(mismatched)[:5])}")
    elif confirmed:
        result.notes.append(f"key: confirmed against {confirmed} journaled request(s)")
    else:
        result.notes.append("key: well-formed, but no journaled request could confirm it belongs to this database")
    if newer:
        result.notes.append(f"journal: {newer} request(s) newer than the database snapshot")


def verify_backup(folder: Path) -> Verification:
    folder = Path(folder)
    result = Verification(folder)
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        result.problems.append(f"no {MANIFEST_NAME}: not a ForgeVigil backup, or an unfinished one")
        return result
    except (OSError, ValueError) as exc:
        result.problems.append(f"{MANIFEST_NAME} cannot be read ({exc})")
        return result
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("format") not in ("forgevigil.backup.v1", BACKUP_SCHEMA_VERSION) or not isinstance(files, dict):
        result.problems.append(f"{MANIFEST_NAME} is not a {BACKUP_SCHEMA_VERSION} manifest")
        return result
    result.manifest = manifest
    if "database" not in files:
        result.problems.append("the manifest lists no database")
        return result

    present: dict[str, Path] = {}
    for role, entry in sorted(files.items()):
        name = entry.get("name") if isinstance(entry, dict) else None
        if not _plain_name(name):
            result.problems.append(f"{role}: the manifest names {name!r}, which is not a file in this backup")
            continue
        path = folder / name
        if not path.is_file():
            result.problems.append(f"{role}: {name} is missing")
            continue
        if path.stat().st_size != entry.get("bytes") or _sha256(path) != entry.get("sha256"):
            result.problems.append(f"{role}: {name} differs from the manifest (altered or damaged)")
            continue
        present[role] = path
    if result.problems:
        return result

    database = present["database"]
    try:
        facts = database_facts(database)
    except (sqlite3.Error, ValueError, TypeError) as exc:
        result.problems.append(f"database: cannot be read as a ForgeVigil store ({exc})")
        return result
    if facts["integrity"] != "ok":
        result.problems.append(f"database: SQLite integrity check failed ({facts['integrity']})")
    if facts["store_schema"] in _OLDER_STORE_SCHEMAS:
        result.notes.append(f"database: store schema {facts['store_schema']}; serve upgrades it after a restore")
    elif facts["store_schema"] != STORE_SCHEMA_VERSION:
        result.problems.append(f"database: unknown store schema {facts['store_schema']!r}")
    expected_format = BACKUP_SCHEMA_VERSION if facts["store_schema"] == STORE_SCHEMA_VERSION else "forgevigil.backup.v1"
    if manifest.get("format") != expected_format or manifest.get("store_schema") != facts["store_schema"]:
        result.problems.append("database: backup format and store schema do not match")
    if facts["counts"] != manifest.get("counts"):
        result.problems.append("database: row counts differ from the manifest")

    key = None
    if "key" in present:
        if present["key"].name != key_path_for(database).name:
            result.problems.append(f"key: named {present['key'].name}, but this database needs {key_path_for(database).name}")
            return result
        try:
            key = load_key(database)
        except DigestKeyError as exc:
            result.problems.append(f"key: {exc}")
            return result
        if "journal" in present:
            _check_key_against_journal(key, present["journal"], facts["receipts"], result)
        else:
            result.notes.append("key: well-formed; no journal in this backup to confirm it belongs to the database")
    elif facts["keyed_digests"]:
        result.problems.append("key: the database has keyed fingerprints but the backup has no key; serve could not start")
    if facts["store_schema"] == STORE_SCHEMA_VERSION:
        from .registry import verify_database_authority
        conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            confirmed = verify_database_authority(conn, key)
            if confirmed:
                result.notes.append(f"key: confirmed against {confirmed} pinned delivery context(s)")
        except (ValueError, TypeError, KeyError, sqlite3.Error):
            result.problems.append("database: registry history or delivery bindings are invalid")
        finally:
            conn.close()
    return result


def create_backup(db_path: Path, *, journal_path: Path | None, backup_root: Path = DEFAULT_BACKUP_ROOT,
                  created_at: str | None = None) -> Verification:
    """Write a verified backup folder under backup_root. Returns its verification."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BackupError("database_missing", f"{db_path} does not exist")
    try:
        key = load_key(db_path)
    except DigestKeyError as exc:
        raise BackupError("digest_key_unreadable", str(exc)) from None
    created_at = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"forgevigil-{stamp}-{secrets.token_hex(2)}"
    backup_root = Path(backup_root)
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = backup_root / f".{name}.partial"
    partial.mkdir(mode=0o700)
    try:
        files = {"database": partial / db_path.name}
        _snapshot_database(db_path, files["database"])
        facts = database_facts(files["database"])
        if facts["keyed_digests"] and key is None:
            raise BackupError("digest_key_missing", f"{db_path} has keyed fingerprints but {key_path_for(db_path)} "
                                                    "is missing; a backup without it could never be restored")
        if key is not None:
            files["key"] = key_path_for(files["database"])
            _write_private(files["key"], key_path_for(db_path).read_bytes())
        if journal_path is not None and Path(journal_path).is_file():
            files["journal"] = partial / Path(journal_path).name
            _write_private(files["journal"], Path(journal_path).read_bytes())
        manifest = {
            "format": BACKUP_SCHEMA_VERSION if facts["store_schema"] == STORE_SCHEMA_VERSION else "forgevigil.backup.v1",
            "created_at": created_at,
            "code_version": CODE_VERSION,
            "store_schema": facts["store_schema"],
            "counts": facts["counts"],
            "keyed_digests": facts["keyed_digests"],
            "sources": {role: str(path) for role, path in
                        (("database", db_path), ("journal", journal_path)) if path is not None},
            "files": {role: {"name": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
                      for role, path in files.items()},
        }
        _write_private(partial / MANIFEST_NAME,
                       (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        verification = verify_backup(partial)
        if not verification.ok:
            raise BackupError("backup_unverified", "; ".join(verification.problems))
        final = backup_root / name
        _rename(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    verification.folder = final
    return verification


def _check_restore_paths(targets: dict[str, Path], files: dict) -> list[Path]:
    """Reject aliases/ancestors between destinations, SQLite side files, lock and staging files."""
    db = targets["database"]
    paths = [db, targets["key"], db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"),
             lock_path_for(db)]
    if "journal" in files:
        paths.append(targets["journal"])
    stages = [target.with_name(f".{target.name}.restoring") for role, target in targets.items() if role in files]
    compared = [path.resolve() for path in paths + stages]
    for index, path in enumerate(compared):
        for other in compared[index + 1:]:
            if path == other or path in other.parents or other in path.parents:
                raise BackupError("target_conflict", "restore destinations, side files and staging paths must "
                                                    "be separate (nothing was changed)")
    return stages


def restore_backup(folder: Path, *, db_path: Path, journal_path: Path) -> list[Path]:
    """Place a verified backup at db_path (and its key and journal). Never overwrites. Returns what was placed."""
    verification = verify_backup(folder)
    if not verification.ok:
        raise BackupError("backup_invalid", "; ".join(verification.problems))
    files = verification.manifest["files"]
    db_path, journal_path = Path(db_path), Path(journal_path)
    targets = {"database": db_path, "key": key_path_for(db_path), "journal": journal_path}
    stages = _check_restore_paths(targets, files)
    guarded = [db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm"),
               key_path_for(db_path)] + ([journal_path] if "journal" in files else []) + stages

    def refuse_existing() -> None:
        existing = [str(path) for path in guarded if path.exists() or path.is_symlink()]
        if existing:
            raise BackupError("target_exists", f"would overwrite {', '.join(existing)}; move them aside first "
                                               "(nothing was changed)")

    refuse_existing()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock = InstanceLock(db_path)
        lock.acquire()
    except InstanceLockError as exc:
        raise BackupError("server_running", f"{exc} (nothing was changed)") from None
    placed: list[Path] = []
    try:
        refuse_existing()  # again, now that no server can start on this database
        try:
            for role in ("key", "journal", "database"):  # the database last: until it appears, nothing looks restored
                if role not in files:
                    continue
                source, target = Path(folder) / files[role]["name"], targets[role]
                staging = target.with_name(f".{target.name}.restoring")
                owned = False
                try:
                    _write_private(staging, source.read_bytes())
                    owned = True
                    if _sha256(staging) != files[role]["sha256"]:
                        raise BackupError("copy_damaged", f"{target} did not copy intact; nothing was left in place")
                    try:
                        os.link(staging, target)  # atomic create-only publication; never replace a late arrival
                    except FileExistsError:
                        raise BackupError("target_appeared", f"{target} appeared during restore; it was preserved") from None
                    placed.append(target)
                finally:
                    if owned:
                        staging.unlink(missing_ok=True)
        except BaseException:
            # All or nothing: remove only what this restore placed. Those paths were proved absent under the lock.
            for path in placed:
                path.unlink(missing_ok=True)
            raise
        if os.name == "posix":
            secure_state_files(db_path)
            if journal_path in placed:
                os.chmod(journal_path, 0o600)
    finally:
        lock.release()
    return placed
