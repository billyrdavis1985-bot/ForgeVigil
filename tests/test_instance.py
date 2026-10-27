"""Checkpoint 08 tests: one server per database, and owner-only state files.

These run real `serve` processes, so they also check that the lock is held for
the server's whole life and released when the process ends, however it ends.
"""

from __future__ import annotations

import http.client
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from forge_vigil.instance import InstanceLock, InstanceLockError, lock_path_for, secure_state_files
from forge_vigil.store import Store
from tests.support import OPERATOR_TOKEN

REPO_ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def healthy(port: int) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            conn.request("GET", "/health")
            return conn.getresponse().status == 200
        finally:
            conn.close()
    except OSError:
        return False


class InstanceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-instance-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "state.sqlite3"

    def serve(self, port: int) -> subprocess.Popen:
        env = dict(os.environ, FORGEVIGIL_TOKEN=OPERATOR_TOKEN)
        return subprocess.Popen(
            [sys.executable, "-m", "forge_vigil", "serve", "--db", str(self.db_path), "--port", str(port)],
            cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )

    def wait_healthy(self, proc: subprocess.Popen, port: int) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if healthy(port):
                return
            if proc.poll() is not None:
                self.fail(f"server exited early ({proc.returncode}): {proc.stderr.read()}")
            time.sleep(0.1)
        self.fail("server did not become healthy")

    def stop(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()  # the hardest way a server can end: no cleanup code runs
        proc.wait(timeout=20)
        proc.stderr.close()

    def test_a_second_lock_on_the_same_database_is_refused(self):
        first = InstanceLock(self.db_path)
        first.acquire()
        with self.assertRaises(InstanceLockError) as caught:
            InstanceLock(self.db_path).acquire()
        self.assertIn(str(self.db_path), str(caught.exception))
        with InstanceLock(self.tmp / "other.sqlite3"):  # a different database is unaffected
            pass
        first.release()
        with InstanceLock(self.db_path):
            pass
        self.assertTrue(lock_path_for(self.db_path).exists())  # left in place on purpose

    def test_the_lock_is_released_when_its_process_dies(self):
        holder = subprocess.Popen(
            [sys.executable, "-u", "-c",
             "import sys, time; from forge_vigil.instance import InstanceLock; "
             "InstanceLock(sys.argv[1]).acquire(); print('locked'); time.sleep(60)",
             str(self.db_path)],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        with self.assertRaises(InstanceLockError):
            InstanceLock(self.db_path).acquire()
        holder.kill()
        holder.wait(timeout=20)
        holder.stdout.close()
        deadline = time.monotonic() + 10  # Windows can take a moment to drop a dead process's locks
        while True:
            try:
                InstanceLock(self.db_path).acquire()
                break
            except InstanceLockError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)

    def test_serve_refuses_a_database_another_process_holds_and_touches_nothing(self):
        with InstanceLock(self.db_path):
            env = dict(os.environ, FORGEVIGIL_TOKEN=OPERATOR_TOKEN)
            proc = subprocess.run(
                [sys.executable, "-m", "forge_vigil", "serve", "--db", str(self.db_path), "--port", str(free_port())],
                cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("another ForgeVigil server is already using", proc.stderr)
        self.assertFalse(self.db_path.exists())  # refused before the database was opened

    def test_a_running_server_holds_the_lock_until_it_ends(self):
        first_port, second_port = free_port(), free_port()
        first = self.serve(first_port)
        self.addCleanup(self.stop, first)
        self.wait_healthy(first, first_port)

        second = self.serve(second_port)
        _, err = second.communicate(timeout=30)
        self.assertEqual(second.returncode, 2, err)
        self.assertIn("another ForgeVigil server is already using", err)
        self.assertTrue(healthy(first_port))  # the running server is unaffected

        self.stop(first)
        third = self.serve(second_port)  # the lock is free again once the first server is gone
        self.addCleanup(self.stop, third)
        self.wait_healthy(third, second_port)
        if os.name == "posix":
            for path in (self.db_path, lock_path_for(self.db_path)):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)

    def test_an_unopenable_lock_file_is_reported_as_such(self):
        missing_folder = self.tmp / "no-such-folder" / "state.sqlite3"
        with self.assertRaises(InstanceLockError) as caught:
            InstanceLock(missing_folder).acquire()
        self.assertIn("cannot open the lock file", str(caught.exception))
        self.assertNotIn("already using", str(caught.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX file modes; Windows uses the folder's access list")
    def test_state_files_are_owner_only(self):
        secure_state_files(self.db_path)
        self.assertEqual(stat.S_IMODE(self.db_path.stat().st_mode), 0o600)
        Store(self.db_path)
        conn = sqlite3.connect(self.db_path)  # hold a connection so the -wal and -shm files exist
        self.addCleanup(conn.close)
        conn.execute("INSERT INTO meta (key, value) VALUES ('probe', 'x')")
        conn.commit()
        for suffix in ("-wal", "-shm"):
            side = self.db_path.with_name(self.db_path.name + suffix)
            self.assertEqual(stat.S_IMODE(side.stat().st_mode), 0o600, side)

        loose = self.tmp / "loose.sqlite3"
        loose.write_bytes(b"")
        os.chmod(loose, 0o644)
        secure_state_files(loose)  # an existing database is tightened too
        self.assertEqual(stat.S_IMODE(loose.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
