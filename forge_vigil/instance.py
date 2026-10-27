"""One server per database file.

At startup a service resolves whatever a previous process left unfinished: it
holds in-progress requests for REVIEW and marks in-flight spend as unknown. A
second server on the same file would do that to requests the first one is
still working on. So `serve` holds an exclusive operating-system lock on a
sibling `<db>.lock` file for as long as it runs.

The operating system releases the lock when the process exits, however it
exits, so a crash never leaves a stale lock. The lock file itself is left in
place; deleting it would let two processes lock different files.

`review` and `report` take no lock: they are meant to run alongside `serve`,
and SQLite transactions keep them consistent with it.

On POSIX systems the state files are also made readable by their owner only.
SQLite gives its -wal and -shm files the permissions of the database file, so
securing that one file covers all three. On Windows, files inherit the folder's
access list, which under the user's profile is already owner-only; nothing is
changed there.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

# How a non-blocking lock reports that someone else holds it: flock raises BlockingIOError (EAGAIN or
# EWOULDBLOCK); Windows _locking sets EACCES (EDEADLOCK is its blocking-mode timeout). Any other error is a
# real failure, not "in use".
_HELD_ERRNOS = frozenset({errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK})


class InstanceLockError(Exception):
    """Another process holds the lock; nothing was started."""


def lock_path_for(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".lock")


class InstanceLock:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.path = lock_path_for(self.db_path)
        self._fd: int | None = None

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        except OSError as exc:
            raise InstanceLockError(f"cannot open the lock file {self.path} ({exc.strerror})") from None
        try:
            _lock(fd)
        except OSError as exc:
            os.close(fd)
            if exc.errno in _HELD_ERRNOS:
                raise InstanceLockError(f"another ForgeVigil server is already using {self.db_path}") from None
            raise InstanceLockError(f"cannot lock {self.path} ({exc.strerror})") from None
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


def secure_state_files(db_path: Path) -> None:
    """POSIX: create the database owner-only, or tighten an existing one, its -wal and -shm files and its key."""
    if os.name != "posix":
        return
    db_path = Path(db_path)
    if not db_path.exists():
        os.close(os.open(db_path, os.O_RDWR | os.O_CREAT, 0o600))  # SQLite treats an empty file as new
    for suffix in ("", "-wal", "-shm", ".key"):
        path = db_path.with_name(db_path.name + suffix)
        if path.exists():
            os.chmod(path, 0o600)


if os.name == "nt":
    import msvcrt

    # Windows byte-range locks belong to one file handle, so a second open of the same file is refused
    # even inside one process. Byte 0 may be locked although the file is empty.
    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    # flock locks belong to one open file description, so a second open is refused even in one process.
    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
