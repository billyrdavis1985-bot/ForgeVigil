"""New-file JSON exports for report and evaluation; never replace earlier evidence.

Reserve the destination before assessment and keep that descriptor until saving ends.
An interrupted or failed save can leave an empty/partial file: retain it for inspection,
report failure, and require a fresh destination. This is not an atomic publication API.
"""

from __future__ import annotations

import errno
import json
import ntpath
import os
import warnings
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from typing import TextIO

_IS_WINDOWS = os.name == "nt"


def _is_reserved_name(part: str) -> bool:
    """Windows reserved-name check without deprecated APIs.

    ntpath.isreserved exists on every platform; the pathlib spelling is
    deprecated on 3.14 and gone on 3.15. The fallback covers interpreters
    predating ntpath.isreserved.
    """
    isreserved = getattr(ntpath, "isreserved", None)
    if isreserved is not None:
        return bool(isreserved(part))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return bool(PureWindowsPath(part).is_reserved())


def check_output(path: Path | None, protected=()) -> Path | None:
    """Read-only checks; exclusive creation below closes the leaf check/create race."""
    if path is None:
        return None
    # Win32 device/extended namespaces can bypass ordinary filename checks.
    if _IS_WINDOWS and str(PureWindowsPath(path)).startswith(("\\\\.\\", "\\\\?\\")):
        raise OSError(errno.EINVAL, "Windows device/extended output namespace is not supported", str(path))
    # GetFullPathName on Windows may remove trailing dots/spaces. Inspect the
    # supplied components first, including a relative filename with no anchor.
    windows = PureWindowsPath(path)
    windows_parts = windows.parts[1:] if windows.anchor else windows.parts
    if _IS_WINDOWS and any(
        ":" in part or part.endswith((".", " ")) or _is_reserved_name(part)
        for part in windows_parts if part != ".."
    ):
        raise OSError(errno.EINVAL, "reserved Windows output name", str(path))
    path = Path(os.path.abspath(path))
    if path.is_dir():
        raise IsADirectoryError(errno.EISDIR, "output is a folder, not a file", str(path))
    if os.path.lexists(path):
        raise FileExistsError(errno.EEXIST, "output already exists; choose a new file", str(path))
    if not path.parent.is_dir():
        raise FileNotFoundError(errno.ENOENT, "the output folder does not exist", str(path))
    if any(parent.is_symlink() for parent in path.parents):
        raise OSError(errno.EINVAL, "output parent must not be a symbolic link", str(path))
    try:
        canonical = path.resolve()
        if any(canonical == Path(item).resolve() for item in protected if item is not None):
            raise OSError(errno.EINVAL, "output overlaps protected input or database state", str(path))
    except RuntimeError:
        raise OSError(errno.EINVAL, "cannot resolve output path", str(path)) from None
    return path


@contextmanager
def new_output(path: Path | None, protected=()):
    path = check_output(path, protected)
    if path is None:
        yield None
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o600)
    try:
        stream = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
    except BaseException:
        os.close(fd)
        raise
    with stream:
        yield stream


def write_json(stream: TextIO | None, value: dict) -> None:
    if stream is None:
        return
    json.dump(value, stream, indent=2, sort_keys=True)
    stream.flush()
    os.fsync(stream.fileno())
