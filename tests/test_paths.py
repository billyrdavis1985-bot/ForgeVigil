"""Checkpoint 15: database aliases and file publication must preserve other state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from forge_vigil import backup as backup_module
from forge_vigil import review_cases as cases_module
from forge_vigil.assessment import fixed_clean_assessor
from forge_vigil.backup import BackupError, create_backup, restore_backup
from forge_vigil.client import append_journal
from forge_vigil.digests import key_path_for
from forge_vigil.fixtures import default_fixtures
from forge_vigil.instance import InstanceLock, InstanceLockError
from forge_vigil.review import decide
from forge_vigil.review_cases import ExportError, export_case
from forge_vigil.schema import parse_request
from forge_vigil.service import ForgeVigilService
from forge_vigil.store import Store
from tests.support import OPERATOR_TOKEN, valid_payload, permission_test
from tests.test_instance import free_port, healthy, remove_tree, wait_until_free

REPO_ROOT = Path(__file__).resolve().parents[1]
POSIX_LINKS = unittest.skipUnless(os.name == "posix", "symbolic-link tests; Windows may need Developer Mode")


class PathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="forgevigil-paths-"))
        self.addCleanup(remove_tree, self.tmp)
        self.db = self.tmp / "live.sqlite3"
        self.journal = self.tmp / "sent.jsonl"
        self.payload = valid_payload(approval_ref=None)
        service = ForgeVigilService(Store(self.db), fixed_clean_assessor())
        receipt = service.submit("operator", parse_request(json.dumps(self.payload).encode())).receipt
        self.assertEqual(receipt["disposition"], "REVIEW")
        decide(Store(self.db), default_fixtures(), actor_id="operator", request_id=self.payload["request_id"],
               decision="release", reviewer="billy")
        append_journal(self.journal, self.payload)

    def backup(self):
        return create_backup(self.db, journal_path=self.journal, backup_root=self.tmp / "backups").folder

    def export(self, path):
        return export_case(Store(self.db, read_only=True), actor_id="operator",
                           request_id=self.payload["request_id"], message_text=self.payload["message"],
                           cases_path=path, exported_at="2026-10-28T00:00:00Z")

    def server(self, db, port):
        proc = subprocess.Popen(
            [sys.executable, "-m", "forge_vigil", "serve", "--db", str(db), "--port", str(port)],
            cwd=REPO_ROOT, env=dict(os.environ, FORGEVIGIL_TOKEN=OPERATOR_TOKEN),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        def stop():
            was_running = proc.poll() is None
            if was_running:
                proc.kill()
            proc.wait(timeout=20)
            proc.stderr.close()
            if was_running:
                wait_until_free(db)
        self.addCleanup(stop)
        return proc

    def wait_started(self, proc, port):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if healthy(port):
                return
            if proc.poll() is not None:
                self.fail(f"server exited: {proc.stderr.read()}")
            time.sleep(0.1)
        self.fail("server did not become healthy")

    @POSIX_LINKS
    def test_database_symlink_cannot_start_a_second_server(self):
        db = self.tmp / "empty.sqlite3"
        alias = self.tmp / "alias.sqlite3"
        alias.symlink_to(db)
        first_port, second_port = free_port(), free_port()
        first = self.server(db, first_port)
        self.wait_started(first, first_port)
        key_before = key_path_for(db).read_bytes()
        second = self.server(alias, second_port)
        deadline = time.monotonic() + 20
        while second.poll() is None and not healthy(second_port) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIsNotNone(second.poll(), "a second server became healthy through the database alias")
        self.assertEqual(second.returncode, 2, second.stderr.read())
        self.assertTrue(healthy(first_port))
        self.assertEqual(key_path_for(db).read_bytes(), key_before)
        self.assertFalse(key_path_for(alias).exists())
        self.assertFalse(alias.with_name(alias.name + ".lock").exists())

    @POSIX_LINKS
    def test_an_alias_server_uses_the_canonical_key_and_replays(self):
        alias = self.tmp / "alias.sqlite3"
        alias.symlink_to(self.db)
        port = free_port()
        proc = self.server(alias, port)
        self.wait_started(proc, port)
        from forge_vigil.client import post
        status, reply = post(port, OPERATOR_TOKEN, self.payload)
        self.assertEqual((status, reply["outcome"], reply["review"]["decision"]), (200, "replayed", "release"))
        self.assertFalse(key_path_for(alias).exists())
        with self.assertRaises(InstanceLockError):
            InstanceLock(self.db).acquire()

    def test_database_hard_links_are_refused_before_locking(self):
        other = self.tmp / "hardlink.sqlite3"
        os.link(self.db, other)
        for path in (self.db, other):
            with self.subTest(path=path.name), self.assertRaises(InstanceLockError):
                with InstanceLock(path):
                    pass
            self.assertFalse(path.with_name(path.name + ".lock").exists())

    def test_restore_preserves_every_preexisting_staging_file(self):
        folder = self.backup()
        for role in ("key", "journal", "database"):
            with self.subTest(role=role):
                parent = self.tmp / role
                parent.mkdir()
                db, journal = parent / "state.sqlite3", parent / "sent.jsonl"
                target = {"database": db, "key": key_path_for(db), "journal": journal}[role]
                staging = target.with_name("." + target.name + ".restoring")
                staging.write_bytes(b"unrelated operator data")
                with self.assertRaises(BackupError) as caught:
                    restore_backup(folder, db_path=db, journal_path=journal)
                self.assertEqual(caught.exception.code, "target_exists")
                self.assertEqual(staging.read_bytes(), b"unrelated operator data")
                self.assertEqual(list(parent.iterdir()), [staging])

    def test_restore_does_not_remove_a_staging_file_it_failed_to_create(self):
        folder = self.backup()
        db = self.tmp / "restore" / "state.sqlite3"
        staging = key_path_for(db).with_name("." + key_path_for(db).name + ".restoring")
        real_write = backup_module._write_private
        def race(path, data):
            path.write_bytes(b"created by another writer")
            real_write(path, data)
        with mock.patch.object(backup_module, "_write_private", side_effect=race):
            with self.assertRaises(OSError):
                restore_backup(folder, db_path=db, journal_path=db.with_name("sent.jsonl"))
        self.assertEqual(staging.read_bytes(), b"created by another writer")
        self.assertFalse(db.exists() or key_path_for(db).exists())

    def test_restore_refuses_a_destination_created_after_its_initial_checks(self):
        folder = self.backup()
        db = self.tmp / "race" / "state.sqlite3"
        journal = db.with_name("sent.jsonl")
        real_write = backup_module._write_private
        def race(path, data):
            real_write(path, data)
            if path.name == "." + db.name + ".restoring":
                db.write_bytes(b"another writer won")
        with mock.patch.object(backup_module, "_write_private", side_effect=race):
            with self.assertRaises(BackupError) as caught:
                restore_backup(folder, db_path=db, journal_path=journal)
        self.assertEqual(caught.exception.code, "target_appeared")
        self.assertEqual(db.read_bytes(), b"another writer won")
        self.assertFalse(journal.exists() or key_path_for(db).exists())
        self.assertFalse(any(p.name.endswith(".restoring") for p in db.parent.iterdir()))

    def test_restore_rejects_overlapping_destinations_before_writing(self):
        folder = self.backup()
        names = ("state.sqlite3", "state.sqlite3.key", "state.sqlite3-wal", "state.sqlite3-shm",
                 "state.sqlite3.lock", ".state.sqlite3.restoring", ".state.sqlite3.key.restoring", "parent")
        for index, name in enumerate(names):
            with self.subTest(name=name):
                parent = self.tmp / f"overlap-{index}" / "parent"
                db = parent / "state.sqlite3"
                journal = parent if name == "parent" else parent / name
                with self.assertRaises(BackupError) as caught:
                    restore_backup(folder, db_path=db, journal_path=journal)
                self.assertEqual(caught.exception.code, "target_conflict")
                self.assertFalse(parent.parent.exists(), "refusal created a destination directory")

    @POSIX_LINKS
    def test_restore_detects_destination_overlap_through_a_parent_symlink(self):
        folder = self.backup()
        real = self.tmp / "real"
        real.mkdir()
        alias = self.tmp / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(BackupError) as caught:
            restore_backup(folder, db_path=real / "state.sqlite3", journal_path=alias / "state.sqlite3")
        self.assertEqual(caught.exception.code, "target_conflict")
        self.assertEqual(list(real.iterdir()), [])

    @POSIX_LINKS
    def test_restore_refuses_dangling_destination_symlinks(self):
        folder = self.backup()
        for role in ("key", "journal", "database"):
            with self.subTest(role=role):
                parent = self.tmp / ("dangling-" + role)
                parent.mkdir()
                db, journal = parent / "state.sqlite3", parent / "sent.jsonl"
                target = {"database": db, "key": key_path_for(db), "journal": journal}[role]
                missing = self.tmp / ("missing-" + role)
                target.symlink_to(missing)
                with self.assertRaises(BackupError) as caught:
                    restore_backup(folder, db_path=db, journal_path=journal)
                self.assertEqual(caught.exception.code, "target_exists")
                self.assertTrue(target.is_symlink())
                self.assertFalse(missing.exists())
                self.assertEqual(list(parent.iterdir()), [target])

    @POSIX_LINKS
    def test_export_refuses_a_partial_symlink_without_touching_its_target(self):
        cases = self.tmp / "cases.json"
        victim = self.tmp / "operator.txt"
        victim.write_bytes(b"unrelated operator data")
        partial = cases.with_name(cases.name + ".partial")
        partial.symlink_to(victim)
        with self.assertRaises(ExportError) as caught:
            self.export(cases)
        self.assertEqual(caught.exception.code, "export_busy")
        self.assertEqual(victim.read_bytes(), b"unrelated operator data")
        self.assertTrue(partial.is_symlink())
        self.assertFalse(cases.exists())

    def test_export_preserves_an_existing_partial_regular_file(self):
        cases = self.tmp / "cases.json"
        partial = cases.with_name(cases.name + ".partial")
        partial.write_bytes(b"another export owns this file")
        with self.assertRaises(ExportError) as caught:
            self.export(cases)
        self.assertEqual(caught.exception.code, "export_busy")
        self.assertEqual(partial.read_bytes(), b"another export owns this file")
        self.assertFalse(cases.exists())

    def test_failed_export_removes_only_its_owned_partial(self):
        cases = self.tmp / "cases.json"
        with mock.patch.object(cases_module.os, "fsync", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                self.export(cases)
        self.assertFalse(cases.exists())
        self.assertFalse(cases.with_name(cases.name + ".partial").exists())

    @POSIX_LINKS
    def test_export_refuses_a_symbolic_link_as_its_case_set(self):
        victim = self.tmp / "other-cases.json"
        victim.write_text(json.dumps({"version": "local.reviews.v1", "cases": []}), encoding="utf-8")
        before = victim.read_bytes()
        cases = self.tmp / "cases.json"
        cases.symlink_to(victim)
        with mock.patch.object(cases_module.os, "open", wraps=os.open) as opened:
            with self.assertRaises(ExportError) as caught:
                self.export(cases)
            creations = [c for c in opened.mock_calls if len(c.args) > 1 and c.args[1] & os.O_CREAT]
            self.assertEqual(creations, [])  # an invalid destination is refused before temporary-file creation
        self.assertEqual(caught.exception.code, "invalid_cases_file")
        self.assertTrue(cases.is_symlink())
        self.assertEqual(victim.read_bytes(), before)
        self.assertFalse(cases.with_name(cases.name + ".partial").exists())

    @POSIX_LINKS
    def test_export_refuses_a_case_set_changed_to_a_symlink_during_its_write(self):
        cases = self.tmp / "cases.json"
        victim = self.tmp / "operator.txt"
        victim.write_bytes(b"operator data")
        def race(fd):
            cases.symlink_to(victim)
        with mock.patch.object(cases_module.os, "fsync", side_effect=race):
            with self.assertRaises(ExportError) as caught:
                self.export(cases)
        self.assertEqual(caught.exception.code, "invalid_cases_file")
        self.assertTrue(cases.is_symlink())
        self.assertEqual(victim.read_bytes(), b"operator data")
        self.assertFalse(cases.with_name(cases.name + ".partial").exists())

    def test_failed_private_backup_write_removes_only_the_file_it_created(self):
        target = self.tmp / "private"
        with mock.patch.object(backup_module.os, "fsync", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                backup_module._write_private(target, b"partial data")
        self.assertFalse(target.exists())
        target.write_bytes(b"someone else's file")
        with self.assertRaises(FileExistsError):
            backup_module._write_private(target, b"replacement")
        self.assertEqual(target.read_bytes(), b"someone else's file")

    @unittest.skipUnless(os.name == "posix", "POSIX file mode")
    @permission_test
    def test_exported_message_files_are_owner_only(self):
        cases = self.tmp / "cases.json"
        self.export(cases)
        self.assertEqual(cases.stat().st_mode & 0o777, 0o600)
        self.assertFalse(cases.with_name(cases.name + ".partial").exists())


if __name__ == "__main__":
    unittest.main()
