"""Isolated read-only materialization of a merge-candidate tree (TECH-DESIGN D2)."""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mergegate.core.errors import WorkspaceError
from mergegate.core.git import GitCliError, isolated_git_env, run_git
from mergegate.core.identity import MergeCandidateIdentity

WORKSPACE_MARKER_NAME = ".mergegate-workspace"
_WORKSPACE_DIR_PREFIX = "mergegate-ws-"


class ReviewWorkspace(BaseModel):
    """A disposable directory containing the merge tree, chmod'd read-only."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    root: Path
    merge_tree_oid: str
    owner_note: str = Field(
        description="Dedicated unprivileged runtime user (server) or invoking user (CLI)."
    )


def _protected_paths() -> frozenset[Path]:
    home = Path.home().resolve()
    tmp = Path(tempfile.gettempdir()).resolve()
    return frozenset(
        {
            Path("/"),
            Path("/home"),
            Path("/usr"),
            Path("/etc"),
            Path("/var"),
            Path("/tmp"),
            tmp,
            home,
        }
    )


def assert_acceptable_workspace_destination(path: Path) -> None:
    resolved = path.resolve()
    if resolved in _protected_paths():
        raise WorkspaceError(f"refusing to use protected path as workspace: {resolved}")
    if resolved.parts[:2] == ("/", "home") and len(resolved.parts) == 3:
        raise WorkspaceError(f"refusing to use a user home directory as workspace: {resolved}")


def _marker_path(root: Path) -> Path:
    return root / WORKSPACE_MARKER_NAME


def _chmod_if_possible(path: Path, mode: int) -> None:
    try:
        path.chmod(mode, follow_symlinks=False)
    except (NotImplementedError, OSError):
        path.chmod(mode)


def freeze_directory_read_only(root: Path) -> None:
    """Files 0444, directories 0555. Does not follow symlinks."""

    for dirpath, _dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        directory = Path(dirpath)
        for name in filenames:
            file_path = directory / name
            if file_path.is_symlink():
                continue
            _chmod_if_possible(file_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        _chmod_if_possible(
            directory,
            stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )


def thaw_directory_writable(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory = Path(dirpath)
        _chmod_if_possible(
            directory,
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR,
        )
        for name in filenames:
            file_path = directory / name
            if file_path.is_symlink():
                continue
            _chmod_if_possible(file_path, stat.S_IRUSR | stat.S_IWUSR)


async def _extract_tree_archive(repository: Path, tree_oid: str, destination: Path) -> None:
    fd, raw_name = tempfile.mkstemp(prefix="mergegate-archive-", suffix=".tar")
    os.close(fd)
    tar_path = Path(raw_name)
    try:
        try:
            await run_git(
                "archive",
                "--format=tar",
                f"--output={tar_path}",
                tree_oid,
                cwd=repository,
            )
        except GitCliError as exc:
            raise WorkspaceError(f"git archive of merge tree {tree_oid} failed: {exc}") from exc
        process = await asyncio.create_subprocess_exec(
            "tar",
            "-xf",
            str(tar_path),
            "-C",
            str(destination),
            env={"PATH": isolated_git_env()["PATH"], "LC_ALL": "C"},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise WorkspaceError(f"tar extract of merge tree {tree_oid} failed: {detail}")
    finally:
        try:
            os.unlink(tar_path)
        except FileNotFoundError:
            pass


async def materialize_read_only_workspace(
    candidate: MergeCandidateIdentity,
    *,
    destination: Path | None = None,
    owner_note: str = "invoking user",
) -> ReviewWorkspace:
    """``git archive <tree>`` then ``tar -x`` into a fresh directory, then chmod read-only."""

    repository = Path(candidate.source_repository)
    created_destination = destination is None
    if destination is None:
        destination = Path(tempfile.mkdtemp(prefix=_WORKSPACE_DIR_PREFIX))
    else:
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise WorkspaceError(f"workspace destination is not empty: {destination}")

    assert_acceptable_workspace_destination(destination)
    try:
        await _extract_tree_archive(repository, candidate.merge_tree_oid, destination)
        _marker_path(destination).write_text(candidate.merge_tree_oid + "\n", encoding="utf-8")
        freeze_directory_read_only(destination)
    except Exception:
        if destination.exists():
            thaw_directory_writable(destination)
            if created_destination:
                shutil.rmtree(destination)
        raise
    return ReviewWorkspace(
        root=destination,
        merge_tree_oid=candidate.merge_tree_oid,
        owner_note=owner_note,
    )


async def cleanup_review_workspace(workspace: ReviewWorkspace) -> None:
    """Thaw and remove a workspace we created. Refuses unmarked or protected paths."""

    root = workspace.root.resolve()
    assert_acceptable_workspace_destination(root)
    marker = _marker_path(root)
    if not marker.is_file():
        raise WorkspaceError(f"refusing to delete {root}: missing {WORKSPACE_MARKER_NAME} marker")
    thaw_directory_writable(root)
    shutil.rmtree(root)
