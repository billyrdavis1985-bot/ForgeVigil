"""Checkpoint 13 tests: backup and restore.

A backup must hold everything a running server has committed, including what still
sits in the WAL. It must refuse to exist incomplete, prove its key belongs to its
database, and never write into itself when checked. A restore must never overwrite
anything, never race a running server, and never place an unverified backup.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge_vigil import backup as backup_module
from forge_vigil.backup import COUNTED_TABLES, MANIFEST_NAME, BackupError, create_backup, restore_backup, verify_backup
from forge_vigil.client import submit
from forge_vigil.digests import key_path_for
from forge_vigil.fixtures import default_fixtures
from forge_vigil.instance import InstanceLock
from forge_vigil.review import decide
from forge_vigil.store import Store
from tests.support import OPERATOR_TOKEN, Harness, valid_payload, permission_test
from tests.test_instance import files_held_open_under, remove_tree

REPO_ROOT = Path(__file__).resolve().parents[1]

SENT = (  # request_id, approval_ref: one ALLOW and two held for review
    ("req-allow", "HR-2026-118"),
    ("req-held", None),
    ("req-unknown", "HR-2026-999"),
)


def snapshot(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="forgevigil-backup-"))
        self.addCleanup(remove_tree, self.tmp)  # registered first, so it runs after everything is closed
        self.addCleanup(lambda: self.assertEqual(files_held_open_under(self.tmp), [], "a test left a file open"))
        self.db = self.tmp / "live" / "forgevigil.sqlite3"
        self.db.parent.mkdir()
        self.journal = self.tmp / "live" / "sent.jsonl"
        self.root = self.tmp / "backups"

    def message(self, request_id: str) -> str:
        return f"Please send the spec ({request_id}). Thanks."

    def serve_and_submit(self, *, hold_wal: bool = False) -> Harness:
        """A running server with three journaled requests and one operator decision.

        `hold_wal` keeps a reader open throughout, as a busy server's other connections do, so committed
        pages stay in the WAL instead of being folded into the database file when the last connection closes."""
        harness = Harness(self.db)
        self.addCleanup(harness.stop)
        if hold_wal:
            self.reader = sqlite3.connect(self.db)
            self.addCleanup(self.reader.close)
            self.reader.execute("SELECT COUNT(*) FROM requests").fetchone()
        for request_id, approval in SENT:
            result = submit(harness.port, OPERATOR_TOKEN,
                            valid_payload(request_id=request_id, approval_ref=approval, message=self.message(request_id)),
                            self.journal, submitted_at="2026-10-27T00:00:00Z")
            self.assertTrue(result["journaled"], result)
        decide(Store(self.db), default_fixtures(), actor_id="operator", request_id="req-held", decision="release",
               reviewer="billy")
        return harness

    def good_backup(self) -> Path:
        self.serve_and_submit().stop()
        return create_backup(self.db, journal_path=self.journal, backup_root=self.root).folder

    def damaged_copy(self, folder: Path, name: str) -> Path:
        copy = self.tmp / name / folder.name
        shutil.copytree(folder, copy)
        return copy

    @permission_test
    def test_a_backup_taken_while_serving_holds_everything_and_restores(self):
        self.serve_and_submit(hold_wal=True)
        reader = self.reader
        self.assertGreater(self.db.with_name(self.db.name + "-wal").stat().st_size, 0)

        result = subprocess.run([sys.executable, "-m", "forge_vigil", "backup", "create", "--db", str(self.db),
                                 "--journal", str(self.journal), "--to", str(self.root)],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(": OK", result.stdout)
        self.assertIn("key: confirmed against 3 journaled request(s)", result.stdout)
        (folder,) = list(self.root.iterdir())  # nothing else, no .partial left behind
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted([self.db.name, key_path_for(self.db).name, self.journal.name, MANIFEST_NAME]))

        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        live = {table: reader.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in COUNTED_TABLES}
        self.assertEqual(manifest["counts"], live)  # including what was only in the WAL
        self.assertEqual(live["reviews"], 1)
        copy = sqlite3.connect((folder / self.db.name).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        self.addCleanup(copy.close)
        self.assertEqual(copy.execute("PRAGMA journal_mode").fetchone()[0], "delete")  # one self-contained file
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
            for path in folder.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)

        restored = self.tmp / "restored" / "forgevigil.sqlite3"
        placed = restore_backup(folder, db_path=restored, journal_path=restored.with_name("sent.jsonl"))
        self.assertEqual([p.name for p in placed], [key_path_for(restored).name, "sent.jsonl", restored.name])
        again = Harness(restored)  # the restored key and database still recognise every earlier request
        self.addCleanup(again.stop)
        replay = submit(again.port, OPERATOR_TOKEN,
                        valid_payload(request_id="req-held", approval_ref=None, message=self.message("req-held")),
                        None, submitted_at="t")
        self.assertEqual((replay["status"], replay["reply"]["outcome"], replay["reply"]["review"]["decision"]),
                         (200, "replayed", "release"))

    def test_a_keyed_database_without_its_key_is_refused_and_leaves_nothing(self):
        self.serve_and_submit().stop()
        key = key_path_for(self.db)
        key.rename(key.with_name("moved-aside.key"))
        with self.assertRaises(BackupError) as caught:
            create_backup(self.db, journal_path=self.journal, backup_root=self.root)
        self.assertEqual(caught.exception.code, "digest_key_missing")
        self.assertEqual(list(self.root.iterdir()), [])  # no backup, complete or partial

        key.write_text("not a key\n", encoding="ascii")
        with self.assertRaises(BackupError) as caught:
            create_backup(self.db, journal_path=self.journal, backup_root=self.root)
        self.assertEqual(caught.exception.code, "digest_key_unreadable")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_verify_finds_damage_and_never_writes(self):
        folder = self.good_backup()
        before = snapshot(folder)
        verification = verify_backup(folder)
        self.assertTrue(verification.ok, verification.problems)
        self.assertEqual(snapshot(folder), before)  # checking a backup writes nothing into it

        def manifest_of(path):
            return json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))

        def save_manifest(path, manifest):
            (path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

        altered = self.damaged_copy(folder, "altered")
        with open(altered / self.journal.name, "ab") as handle:
            handle.write(b"\n")  # harmless to the journal's readers, but not what was backed up
        wrong_key = self.damaged_copy(folder, "wrong-key")
        (wrong_key / key_path_for(self.db).name).write_text("ab" * 32 + "\n", encoding="ascii")
        manifest = manifest_of(wrong_key)  # the manifest made consistent, so only the key check can tell
        manifest["files"]["key"]["sha256"] = hashlib.sha256(
            (wrong_key / key_path_for(self.db).name).read_bytes()).hexdigest()
        save_manifest(wrong_key, manifest)
        outside = self.damaged_copy(folder, "outside")
        (outside / self.db.name).rename(outside.parent / self.db.name)  # a matching file, but outside the backup
        manifest = manifest_of(outside)
        manifest["files"]["database"]["name"] = "../" + self.db.name
        save_manifest(outside, manifest)
        keyless = self.damaged_copy(folder, "keyless")
        (keyless / key_path_for(self.db).name).unlink()
        manifest = manifest_of(keyless)
        del manifest["files"]["key"]
        save_manifest(keyless, manifest)
        missing = self.damaged_copy(folder, "missing")
        (missing / key_path_for(self.db).name).unlink()
        unfinished = self.damaged_copy(folder, "unfinished")
        (unfinished / MANIFEST_NAME).unlink()

        for path, expected in (
            (altered, "journal: sent.jsonl differs from the manifest"),
            (wrong_key, "does not reproduce its stored fingerprint with this key"),
            (outside, "which is not a file in this backup"),
            (keyless, "has keyed fingerprints but the backup has no key"),
            (missing, "key: forgevigil.sqlite3.key is missing"),
            (unfinished, "no manifest.json"),
        ):
            with self.subTest(path.parent.name):
                verification = verify_backup(path)
                self.assertFalse(verification.ok)
                self.assertIn(expected, " | ".join(verification.problems))

        result = subprocess.run([sys.executable, "-m", "forge_vigil", "backup", "verify", str(wrong_key)],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("NOT USABLE", result.stdout)
        self.assertIn("PROBLEM: key:", result.stdout)

    def test_restore_never_overwrites_never_races_a_server_and_never_places_a_bad_backup(self):
        folder = self.good_backup()

        def targets(name):
            db = self.tmp / name / "forgevigil.sqlite3"
            db.parent.mkdir()
            return db, db.with_name("sent.jsonl")

        occupied, occupied_journal = targets("occupied")
        occupied.write_bytes(b"someone's database")
        with self.assertRaises(BackupError) as caught:
            restore_backup(folder, db_path=occupied, journal_path=occupied_journal)
        self.assertEqual(caught.exception.code, "target_exists")
        self.assertEqual(occupied.read_bytes(), b"someone's database")
        self.assertFalse(key_path_for(occupied).exists() or occupied_journal.exists())

        busy, busy_journal = targets("busy")
        with InstanceLock(busy):  # as if serve had just started on this path
            with self.assertRaises(BackupError) as caught:
                restore_backup(folder, db_path=busy, journal_path=busy_journal)
        self.assertEqual(caught.exception.code, "server_running")
        self.assertFalse(busy.exists() or key_path_for(busy).exists() or busy_journal.exists())

        damaged = self.damaged_copy(folder, "damaged")
        with open(damaged / self.journal.name, "ab") as handle:
            handle.write(b"\n")
        fresh, fresh_journal = targets("fresh")
        with self.assertRaises(BackupError) as caught:
            restore_backup(damaged, db_path=fresh, journal_path=fresh_journal)
        self.assertEqual(caught.exception.code, "backup_invalid")
        self.assertFalse(fresh.exists() or key_path_for(fresh).exists() or fresh_journal.exists())

    def test_a_restore_that_fails_partway_leaves_nothing_behind(self):
        folder = self.good_backup()
        target = self.tmp / "partway" / "forgevigil.sqlite3"
        journal = target.with_name("sent.jsonl")
        real_write = backup_module._write_private
        calls = []

        def fail_on_the_journal(path, data):
            calls.append(path.name)
            if len(calls) == 2:  # the key is already in place; the journal copy fails
                raise OSError(28, "No space left on device")
            real_write(path, data)

        with mock.patch("forge_vigil.backup._write_private", side_effect=fail_on_the_journal):
            with self.assertRaises(OSError):
                restore_backup(folder, db_path=target, journal_path=journal)
        self.assertEqual(calls[0], "." + key_path_for(target).name + ".restoring")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), [target.name + ".lock"])  # only the lock file
        self.assertEqual([p.name for p in restore_backup(folder, db_path=target, journal_path=journal)],
                         [key_path_for(target).name, "sent.jsonl", target.name])  # and a retry then succeeds


if __name__ == "__main__":
    unittest.main()
