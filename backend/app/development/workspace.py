"""Atomic local export in an operator-owned root, without running generated files.

This is path containment, not an OS sandbox against another process with write access.
"""

import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from app.development.models import Bundle, canonical
from app.portfolio.service import PortfolioConflict


def reject_link(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise PortfolioConflict("Workspace links and reparse points are forbidden")


def checked_root(root: Path) -> Path:
    root = root.absolute()
    if ".." in root.parts:
        raise ValueError("Workspace root must be normalized")
    for path in (*reversed(root.parents), root):
        reject_link(path)
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise PortfolioConflict("Workspace root is not a directory")
    return root.resolve(strict=True)


def expected_files(bundle: Bundle) -> dict[str, bytes]:
    return {
        **{f.path: f.content.encode("utf-8") for f in bundle.files},
        "manifest.json": canonical(bundle.manifest()) + b"\n",
    }


def verify_workspace(target: Path, bundle: Bundle) -> None:
    reject_link(target)
    if not target.is_dir():
        raise PortfolioConflict("Workspace target is not a directory")
    actual: dict[str, bytes] = {}
    expected = expected_files(bundle)
    expected_dirs = {
        str(parent).replace("\\", "/")
        for name in expected
        for parent in Path(name).parents
        if str(parent) != "."
    }
    for directory, subdirs, names in os.walk(target, followlinks=False):
        for name in (*subdirs, *names):
            child = Path(directory) / name
            reject_link(child)
            relative = child.relative_to(target).as_posix()
            if child.is_dir():
                if relative not in expected_dirs:
                    raise PortfolioConflict("Unexpected workspace directory")
            else:
                if relative not in expected or not child.is_file():
                    raise PortfolioConflict("Unexpected workspace file")
                if child.stat().st_size != len(expected[relative]):
                    raise PortfolioConflict("Workspace contents changed")
                actual[relative] = child.read_bytes()
    if actual != expected:
        raise PortfolioConflict("Workspace contents changed or files missing")


def materialize(root: Path, artifact_id: UUID, bundle: Bundle) -> Path:
    root = checked_root(root)
    target = root / str(artifact_id)
    if target.exists() or target.is_symlink():
        verify_workspace(target, bundle)
        return target
    # Only the private random staging directory is cleaned up on failure.
    with TemporaryDirectory(prefix=".jack-", dir=root) as staging_name:
        staging = Path(staging_name)
        if staging.resolve().parent != root:
            raise PortfolioConflict("Staging path escaped workspace root")
        payload = staging / "payload"
        payload.mkdir()
        for name, content in expected_files(bundle).items():
            path = payload.joinpath(*name.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
        verify_workspace(payload, bundle)
        # A racing export is accepted only if its complete contents match.
        try:
            if target.exists() or target.is_symlink():
                verify_workspace(target, bundle)
            else:
                payload.rename(target)
        except OSError:
            if not target.exists():
                raise
            verify_workspace(target, bundle)
    return target
