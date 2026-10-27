"""Checkpoint 08 tests: one server per database, and owner-only state files.

These run real `serve` processes, so they also check that the lock is held for
the server's whole life and released when the process ends, however it ends.
"""

from __future__ import annotations

import http.client
import os
import shutil
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


def wait_until_free(db_path: Path, seconds: float = 10) -> None:
    """Return once the lock can be taken (it is released again at once); fail if it stays held.

    On Windows a venv's python.exe is a launcher that runs the real interpreter as a child, and killing the
    launcher ends that child a moment later. So a lock can outlive the process the test killed, briefly."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with InstanceLock(db_path):
                return
        except InstanceLockError:
            if time.monotonic() > deadline:
                raise AssertionError(f"lock still held {seconds:.0f} s after its process ended") from None
            time.sleep(0.1)


def remove_tree(path: Path, seconds: float = 10) -> None:
    """Windows can keep a just-closed file busy for a moment (a dying child process, or a virus scanner
    opening the new file), so deletion is retried briefly. A file that stays open still fails the test."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def files_held_open_under(path: Path) -> list[str]:
    """Files under `path` this process still has open (Linux only; elsewhere an empty list).

    Windows refuses to delete an open file and Linux does not, so a leaked handle only shows up on
    Windows. Checking /proc/self/fd catches the same mistake here."""
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        return []
    root, held = str(path.resolve()), []
    for entry in fd_dir.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith(root + os.sep):
            held.append(target)
    return held


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
        self.tmp = Path(tempfile.mkdtemp(prefix="forgevigil-instance-"))
        self.addCleanup(remove_tree, self.tmp)  # registered first, so it runs after every server is stopped
        self.addCleanup(lambda: self.assertEqual(files_held_open_under(self.tmp), [], "a test left a file open"))
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
        wait_until_free(self.db_path)  # the server is only really gone once its lock is free

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
        wait_until_free(self.db_path)  # takes and releases the lock, so nothing is left open

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
