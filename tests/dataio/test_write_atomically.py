"""Saving never loses the saved project (E2): the new text goes to a temporary
file first, the old version stays as `.bak`, and a file the user made
read-only is still refused."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from figscribe.io.files import write_atomically


def _only(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_a_first_save_writes_the_file_and_no_backup(tmp_path: Path) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "one")
    assert target.read_text(encoding="utf-8") == "one"
    assert _only(tmp_path) == ["a.figscribe"]


def test_a_later_save_keeps_the_last_version_as_bak(tmp_path: Path) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "one")
    write_atomically(target, "two")
    write_atomically(target, "three")
    assert target.read_text(encoding="utf-8") == "three"
    assert (tmp_path / "a.figscribe.bak").read_text(encoding="utf-8") == "two"
    assert _only(tmp_path) == ["a.figscribe", "a.figscribe.bak"]


def test_a_failure_while_writing_leaves_the_saved_file_as_it_was(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "saved")

    def full_disk(_fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", full_disk)
    with pytest.raises(OSError, match="No space"):
        write_atomically(target, "never arrives")
    assert target.read_text(encoding="utf-8") == "saved"
    assert not [n for n in _only(tmp_path) if n.endswith(".tmp")]


def test_a_failure_at_the_last_step_leaves_the_file_and_no_leftover(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "saved")

    def refuse(*_args):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        write_atomically(target, "new")
    assert target.read_text(encoding="utf-8") == "saved"
    assert not [n for n in _only(tmp_path) if n.endswith(".tmp")]


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits differ")
def test_a_read_only_file_is_refused_and_untouched(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root may write to a read-only file")
    target = tmp_path / "a.figscribe"
    write_atomically(target, "saved")
    target.chmod(stat.S_IRUSR)
    with pytest.raises(PermissionError):
        write_atomically(target, "new")
    assert target.read_text(encoding="utf-8") == "saved"
    assert _only(tmp_path) == ["a.figscribe"]


def test_a_read_only_file_is_refused_on_every_platform(tmp_path: Path) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "saved")
    target.chmod(stat.S_IREAD)
    try:
        if os.access(target, os.W_OK):
            pytest.skip("this account may write to a read-only file")
        with pytest.raises(PermissionError):
            write_atomically(target, "new")
        assert target.read_text(encoding="utf-8") == "saved"
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits differ")
def test_a_new_file_has_the_mode_any_new_file_has(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.write_text("x")
    target = tmp_path / "a.figscribe"
    write_atomically(target, "one")
    assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(plain.stat().st_mode)


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits differ")
def test_the_mode_of_the_file_stays(tmp_path: Path) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "one")
    target.chmod(0o640)
    write_atomically(target, "two")
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need rights")
def test_a_link_to_the_project_stays_a_link(tmp_path: Path) -> None:
    real = tmp_path / "real" / "a.figscribe"
    real.parent.mkdir()
    write_atomically(real, "one")
    link = tmp_path / "link.figscribe"
    link.symlink_to(real)
    write_atomically(link, "two")
    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "two"


def test_text_is_written_as_utf8_with_unix_line_ends(tmp_path: Path) -> None:
    target = tmp_path / "a.figscribe"
    write_atomically(target, "µ\n")
    assert target.read_bytes() == "µ\n".encode()


def test_a_folder_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_atomically(tmp_path / "nodir" / "a.figscribe", "x")


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits differ")
def test_a_folder_that_takes_no_new_file_still_takes_the_project(
    tmp_path: Path,
) -> None:
    """Saving worked there before (B7.4 ran the window on such a folder)."""
    if os.geteuid() == 0:
        pytest.skip("root may write anywhere")
    target = tmp_path / "a.figscribe"
    write_atomically(target, "saved")
    tmp_path.chmod(0o555)
    try:
        write_atomically(target, "new")
        assert target.read_text(encoding="utf-8") == "new"
        assert _only(tmp_path) == ["a.figscribe"]
        with pytest.raises(PermissionError):  # a file that is not there cannot be
            write_atomically(tmp_path / "b.figscribe", "x")
    finally:
        tmp_path.chmod(0o755)


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits differ")
def test_a_backup_that_cannot_be_written_does_not_stop_the_save(
    tmp_path: Path,
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root may write anywhere")
    target = tmp_path / "a.figscribe"
    write_atomically(target, "one")
    write_atomically(target, "two")
    bak = tmp_path / "a.figscribe.bak"
    bak.chmod(stat.S_IREAD)
    write_atomically(target, "three")
    assert target.read_text(encoding="utf-8") == "three"
    assert bak.read_text(encoding="utf-8") == "one"  # the old backup stays
