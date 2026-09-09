"""Isolated read-only Review Worktree materialization (TECH-DESIGN D2).

The merge tree is reconstructed from ``ls-tree`` + blob bytes so ``export-ignore``
and ``export-subst`` cannot omit or rewrite content. The review-worktree marker
lives outside the tree namespace.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.errors import ReviewWorktreeError
from worktree_review.core.git import (
    GitCliError,
    TreeEntry,
    cat_file_batch,
    list_tree_entries,
)
from worktree_review.core.identity import MergeCandidateIdentity

REVIEW_WORKTREE_MARKER_NAME = ".worktree-review-marker"
REVIEW_TREE_DIRECTORY_NAME = "tree"
_REVIEW_WORKTREE_DIR_PREFIX = "worktree-review-"
_REGULAR_FILE_MODES = frozenset({"100644", "100755"})
_SYMLINK_MODE = "120000"
_GITLINK_MODE = "160000"


class ReviewWorktree(BaseModel):
    """A disposable container plus the merge-tree directory, chmod'd read-only."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    root: Path
    container_root: Path
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


def assert_acceptable_review_worktree_destination(path: Path) -> None:
    resolved = path.resolve()
    if resolved in _protected_paths():
        raise ReviewWorktreeError(
            f"refusing to use protected path as a Review Worktree: {resolved}"
        )
    if resolved.parts[:2] == ("/", "home") and len(resolved.parts) == 3:
        raise ReviewWorktreeError(
            f"refusing to use a user home directory as a Review Worktree: {resolved}"
        )


def _marker_path(container_root: Path) -> Path:
    return container_root / REVIEW_WORKTREE_MARKER_NAME


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


def _create_marker_file(path: Path, contents: str) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise ReviewWorktreeError(f"review worktree marker already exists: {path}") from exc
    except OSError as exc:
        raise ReviewWorktreeError(f"cannot create review worktree marker {path}: {exc}") from exc
    try:
        os.write(file_descriptor, contents.encode("utf-8"))
    finally:
        os.close(file_descriptor)


def _marker_is_regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)


def _split_relative_path(relative_path: str) -> tuple[str, ...]:
    posix = relative_path.replace("\\", "/")
    if posix.startswith("/") or posix.endswith("/"):
        raise ReviewWorktreeError(f"unsafe tree path: {relative_path!r}")
    parts = tuple(posix.split("/"))
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ReviewWorktreeError(f"unsafe tree path: {relative_path!r}")
    return parts


def _ensure_directory_without_symlink(path: Path) -> None:
    try:
        status = path.lstat()
    except OSError as exc:
        raise ReviewWorktreeError(f"cannot stat {path}: {exc}") from exc
    if stat.S_ISLNK(status.st_mode):
        raise ReviewWorktreeError(f"refusing to use symlink as directory: {path}")
    if not stat.S_ISDIR(status.st_mode):
        raise ReviewWorktreeError(f"expected directory, found a file: {path}")


def _mkdir_parents_without_following(tree_root: Path, parts: tuple[str, ...]) -> Path:
    current = tree_root
    _ensure_directory_without_symlink(current)
    for part in parts[:-1]:
        current = current / part
        try:
            os.mkdir(current)
        except FileExistsError:
            pass
        _ensure_directory_without_symlink(current)
    return current / parts[-1]


def _write_regular_file(path: Path, data: bytes, *, executable: bool) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags, 0o755 if executable else 0o644)
    except OSError as exc:
        raise ReviewWorktreeError(f"cannot create Review Worktree file {path}: {exc}") from exc
    try:
        os.write(file_descriptor, data)
    finally:
        os.close(file_descriptor)


def _write_symlink(path: Path, target: str) -> None:
    try:
        os.symlink(target, path)
    except OSError as exc:
        raise ReviewWorktreeError(f"cannot create Review Worktree symlink {path}: {exc}") from exc


def _list_materialized_paths(tree_root: Path) -> set[str]:
    relative_paths: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(tree_root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            relative_paths.add(full.relative_to(tree_root).as_posix())
    return relative_paths


def _write_tree_entries(
    tree_root: Path, entries: tuple[TreeEntry, ...], blobs: dict[str, bytes]
) -> None:
    gitlink_paths = tuple(entry.path for entry in entries if entry.mode == _GITLINK_MODE)
    if gitlink_paths:
        raise ReviewWorktreeError(
            "merge tree contains gitlinks (submodules), which stage one does not materialize: "
            + ", ".join(gitlink_paths)
        )
    for entry in entries:
        destination = _mkdir_parents_without_following(tree_root, _split_relative_path(entry.path))
        if entry.mode == _SYMLINK_MODE:
            if entry.object_type != "blob":
                raise ReviewWorktreeError(f"symlink {entry.path} is not a blob")
            _write_symlink(destination, os.fsdecode(blobs[entry.object_id]))
            continue
        if entry.mode in _REGULAR_FILE_MODES:
            if entry.object_type != "blob":
                raise ReviewWorktreeError(f"file {entry.path} is not a blob")
            _write_regular_file(
                destination,
                blobs[entry.object_id],
                executable=entry.mode == "100755",
            )
            continue
        raise ReviewWorktreeError(f"unsupported tree entry mode {entry.mode} at {entry.path}")


def _verify_tree_entries(
    tree_root: Path, entries: tuple[TreeEntry, ...], blobs: dict[str, bytes]
) -> None:
    expected = {entry.path for entry in entries}
    actual = _list_materialized_paths(tree_root)
    if expected != actual:
        raise ReviewWorktreeError(
            "materialized Review Worktree does not match merge tree entries: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    for entry in entries:
        destination = tree_root.joinpath(*_split_relative_path(entry.path))
        try:
            status = destination.lstat()
        except OSError as exc:
            raise ReviewWorktreeError(f"missing materialized path {entry.path}: {exc}") from exc
        expected_bytes = blobs[entry.object_id]
        if entry.mode == _SYMLINK_MODE:
            if not stat.S_ISLNK(status.st_mode):
                raise ReviewWorktreeError(f"expected symlink at {entry.path}")
            if os.fsencode(os.readlink(destination)) != expected_bytes:
                raise ReviewWorktreeError(f"symlink target mismatch at {entry.path}")
            continue
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
            raise ReviewWorktreeError(f"expected regular file at {entry.path}")
        if destination.read_bytes() != expected_bytes:
            raise ReviewWorktreeError(f"blob content mismatch at {entry.path}")
        executable = bool(status.st_mode & stat.S_IXUSR)
        if (entry.mode == "100755") != executable:
            raise ReviewWorktreeError(f"executable bit mismatch at {entry.path}")


async def _materialize_tree(repository: Path, tree_oid: str, tree_root: Path) -> None:
    try:
        entries = await list_tree_entries(tree_oid, repository)
        blob_ids = tuple(
            entry.object_id
            for entry in entries
            if entry.mode in _REGULAR_FILE_MODES or entry.mode == _SYMLINK_MODE
        )
        blobs = await cat_file_batch(blob_ids, repository)
    except FileNotFoundError as exc:
        raise ReviewWorktreeError("git is not installed on PATH") from exc
    except GitCliError as exc:
        raise ReviewWorktreeError(f"cannot read merge tree {tree_oid}: {exc}") from exc
    _write_tree_entries(tree_root, entries, blobs)
    _verify_tree_entries(tree_root, entries, blobs)


def _prepare_container(destination: Path | None) -> tuple[Path, bool]:
    if destination is None:
        container_root = Path(tempfile.mkdtemp(prefix=_REVIEW_WORKTREE_DIR_PREFIX))
        return container_root, True
    container_root = destination.resolve()
    container_root.mkdir(parents=True, exist_ok=True)
    if any(container_root.iterdir()):
        raise ReviewWorktreeError(f"Review Worktree destination is not empty: {container_root}")
    return container_root, False


async def materialize_review_worktree(
    candidate: MergeCandidateIdentity,
    *,
    repository_path: Path,
    destination: Path | None = None,
    owner_note: str = "invoking user",
) -> ReviewWorktree:
    """Materialize merge-tree blobs into a fresh Review Worktree, then chmod read-only.

    Git object reads use ``repository_path``. ``candidate.source_repository`` is identity.
    """

    repository = repository_path
    if not repository.is_dir():
        raise ReviewWorktreeError(f"source repository does not exist: {repository}")
    container_root, created_destination = _prepare_container(destination)
    assert_acceptable_review_worktree_destination(container_root)
    tree_root = container_root / REVIEW_TREE_DIRECTORY_NAME
    try:
        _create_marker_file(
            container_root / REVIEW_WORKTREE_MARKER_NAME, candidate.merge_tree_oid + "\n"
        )
        os.mkdir(tree_root)
        await _materialize_tree(repository, candidate.merge_tree_oid, tree_root)
        freeze_directory_read_only(container_root)
    except Exception:
        if container_root.exists():
            thaw_directory_writable(container_root)
            if created_destination:
                shutil.rmtree(container_root)
        raise
    return ReviewWorktree(
        root=tree_root,
        container_root=container_root,
        merge_tree_oid=candidate.merge_tree_oid,
        owner_note=owner_note,
    )


async def cleanup_review_worktree(review_worktree: ReviewWorktree) -> None:
    """Thaw and remove a Review Worktree we created. Refuses unmarked or protected paths."""

    container_root = review_worktree.container_root.resolve()
    assert_acceptable_review_worktree_destination(container_root)
    tree_root = review_worktree.root.resolve()
    if tree_root.parent != container_root or tree_root.name != REVIEW_TREE_DIRECTORY_NAME:
        raise ReviewWorktreeError(
            f"refusing to delete {container_root}: tree path {tree_root} is not the Review Worktree"
        )
    marker = _marker_path(container_root)
    if not _marker_is_regular_file(marker):
        raise ReviewWorktreeError(
            f"refusing to delete {container_root}: missing regular "
            f"{REVIEW_WORKTREE_MARKER_NAME} marker"
        )
    thaw_directory_writable(container_root)
    shutil.rmtree(container_root)
