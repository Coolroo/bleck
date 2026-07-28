"""Filesystem helpers with consistent, user-facing failure messages."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from bleck import platforms

from .errors import UserError


def read_bytes(path: Path) -> bytes:
    if not path.exists():
        raise UserError(f"no such file: {path}")
    if path.is_dir():
        raise UserError(f"{path} is a directory, not a file")
    return path.read_bytes()


def require_dir(path: Path) -> Path:
    if not path.is_dir():
        raise UserError(f"not a directory: {path}")
    return path


def guard_overwrite(path: Path, force: bool) -> None:
    """Refuse to clobber. These operations produce large, expensive artifacts."""
    if path.exists() and not force:
        raise UserError(f"{path} exists (use --force to overwrite)")


def _on_rmtree_error(func, path: str, _exc) -> None:
    """Retry a failed removal after clearing the read-only bit.

    Windows refuses to delete read-only files, which staged copies inherit.
    """
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    """Delete a directory tree. Never `shutil.rmtree` directly — see above."""
    if platforms.current().strip_readonly_on_delete:
        shutil.rmtree(path, onexc=_on_rmtree_error)
    else:
        shutil.rmtree(path)
