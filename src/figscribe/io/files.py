"""File helpers shared by all source formats."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path


def sha256_of(path: str | Path) -> str:
    """Return the SHA-256 hex digest of the file at `path`."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stored_path(path: Path, base_dir: str | Path) -> str:
    """The path as written into the project: relative to `base_dir`, with
    forward slashes and `..` where the file is not below it, so that a project
    and its data can be moved or shared together. Absolute where a relative path
    would run through the root of the file system: another drive on Windows, or
    another volume (`/Volumes/USB`), which `../../../../Volumes/USB` would not
    survive a move of the project to."""
    path = os.path.abspath(path)
    base = os.path.abspath(base_dir)
    try:
        common = os.path.commonpath([path, base])
        if os.path.dirname(common) == common:  # only the root is shared
            return str(Path(path))
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:  # another drive
        return str(Path(path))


def rebase_path(stored: str, old_dir: str | Path, new_dir: str | Path) -> str:
    """A path stored for a project in `old_dir`, as it is to be stored for the
    same project saved in `new_dir`: the same file."""
    if os.path.abspath(old_dir) == os.path.abspath(new_dir):
        return stored
    return stored_path(resolve_path(stored, old_dir), new_dir)


def resolve_path(stored: str, base_dir: str | Path) -> Path:
    """Inverse of `stored_path`, without the dots of a path to a neighbouring
    folder."""
    path = Path(stored)
    if path.is_absolute():
        return path
    return Path(os.path.abspath(Path(base_dir) / path))


def write_atomically(path: str | Path, text: str) -> None:
    """Write `text` (UTF-8, LF line ends) to `path` so that a failure leaves
    the file as it was: the text goes to a temporary file next to it, which then
    takes its place. The version it replaces stays as `<name>.bak`. A file that
    may not be written is refused, which a plain replace would not do, and a
    link to the file stays a link. In a folder that takes no new files the file is
    written in place, as it always was, and no backup is made."""
    target = Path(os.path.realpath(path))
    exists = target.exists()
    if exists and not os.access(target, os.W_OK):
        raise PermissionError(13, "Permission denied", str(path))
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
    # Opened with the usual mode of a new file (the umask applies), unlike mkstemp.
    try:
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except PermissionError:
        if not exists:
            raise
        # A folder that takes no new file but a project that may be written
        # (saving worked there before): write in place, without a backup.
        target.write_bytes(text.encode("utf-8"))
        return
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(text.encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        if exists:
            shutil.copymode(target, temporary)
            try:
                shutil.copyfile(target, target.with_name(target.name + ".bak"))
            except OSError:
                pass  # a backup that cannot be written must not stop the save
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
