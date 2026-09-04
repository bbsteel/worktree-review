"""System git CLI wrapper. Merge fidelity requires git ≥ 2.38 (TECH-DESIGN D2)."""

from __future__ import annotations

import asyncio
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from worktree_review.core.errors import (
    GitRequiredError,
    InvalidInvocationError,
    WorktreeReviewError,
)

MIN_GIT_VERSION: tuple[int, int, int] = (2, 38, 0)
_VERSION_PATTERN = re.compile(r"git version (\d+)\.(\d+)\.(\d+)")
_HOOKS_DISABLED: tuple[str, ...] = ("-c", "core.hooksPath=/dev/null")


class GitCliError(WorktreeReviewError):
    """A git subprocess failed. Callers decide whether that is invocation or review Error."""


@dataclass(frozen=True)
class GitProcessResult:
    returncode: int
    stdout: str
    stderr: str


def isolated_git_env(environment_overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Minimal env: no user gitconfig, no hooks, no provider/platform tokens."""

    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    if environment_overrides:
        environment.update(environment_overrides)
    return environment


def parse_git_version(version_stdout: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.search(version_stdout)
    if match is None:
        raise GitRequiredError(f"unrecognized git version output: {version_stdout!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


async def invoke_git(
    *args: str,
    cwd: Path,
    environment_overrides: Mapping[str, str] | None = None,
) -> GitProcessResult:
    process = await asyncio.create_subprocess_exec(
        "git",
        *_HOOKS_DISABLED,
        *args,
        cwd=cwd,
        env=isolated_git_env(environment_overrides),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    return GitProcessResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


async def run_git(
    *args: str,
    cwd: Path,
    environment_overrides: Mapping[str, str] | None = None,
) -> str:
    result = await invoke_git(
        *args,
        cwd=cwd,
        environment_overrides=environment_overrides,
    )
    if result.returncode != 0:
        joined = " ".join(("git", *args))
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitCliError(f"{joined} failed (exit {result.returncode}): {detail}")
    return result.stdout


async def require_git_version() -> tuple[int, int, int]:
    try:
        stdout = await run_git("version", cwd=Path.cwd())
    except FileNotFoundError as exc:
        raise GitRequiredError("git is not installed on PATH") from exc
    except GitCliError as exc:
        raise GitRequiredError(str(exc)) from exc
    version = parse_git_version(stdout)
    if version < MIN_GIT_VERSION:
        pretty = ".".join(str(part) for part in version)
        required = ".".join(str(part) for part in MIN_GIT_VERSION)
        raise GitRequiredError(
            f"git {pretty} is too old; Worktree Review requires git >= {required}"
        )
    return version


async def repository_root(cwd: Path) -> Path:
    try:
        stdout = await run_git("rev-parse", "--show-toplevel", cwd=cwd)
    except GitCliError as exc:
        raise InvalidInvocationError(f"{cwd} is not inside a git repository: {exc}") from exc
    return Path(stdout.strip())


async def worktree_is_clean(repository: Path) -> bool:
    stdout = await run_git("status", "--porcelain", cwd=repository)
    return stdout.strip() == ""


async def resolve_commit(ref: str, repository: Path) -> str:
    try:
        stdout = await run_git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=repository)
    except GitCliError as exc:
        raise InvalidInvocationError(f"cannot resolve {ref!r} to a commit: {exc}") from exc
    return stdout.strip()


async def commit_tree_oid(commit: str, repository: Path) -> str:
    return (await run_git("rev-parse", f"{commit}^{{tree}}", cwd=repository)).strip()


async def diff_name_status(
    *,
    from_tree: str,
    to_tree: str,
    repository: Path,
) -> tuple[tuple[str, str], ...]:
    """Return ``((status, path), ...)`` for ``from_tree`` → ``to_tree``.

    Rename detection is off so add+delete pairs stay explicit.
    """

    stdout = await run_git(
        "diff-tree",
        "-r",
        "--name-status",
        "--no-renames",
        from_tree,
        to_tree,
        cwd=repository,
    )
    entries: list[tuple[str, str]] = []
    for line in stdout.splitlines():
        if not line:
            continue
        status, path = line.split("\t", 1)
        entries.append((status[0], path))
    return tuple(entries)


async def git_blob_bytes(spec: str, repository: Path) -> bytes:
    """Read a blob (``commit:path`` or object id) as raw bytes."""

    returncode, stdout_bytes, stderr_bytes = await invoke_git_bytes(
        "cat-file", "-p", spec, cwd=repository
    )
    if returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise GitCliError(f"git cat-file -p {spec} failed: {detail}")
    return stdout_bytes


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_type: str
    object_id: str
    path: str


async def invoke_git_bytes(
    *args: str,
    cwd: Path,
    stdin: bytes | None = None,
    environment_overrides: Mapping[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *_HOOKS_DISABLED,
        *args,
        cwd=cwd,
        env=isolated_git_env(environment_overrides),
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate(input=stdin)
    returncode = process.returncode if process.returncode is not None else -1
    return returncode, stdout_bytes, stderr_bytes


async def list_tree_entries(tree_oid: str, repository: Path) -> tuple[TreeEntry, ...]:
    """List recursive tree entries as recorded in the object database (no export filters)."""

    returncode, stdout_bytes, stderr_bytes = await invoke_git_bytes(
        "ls-tree", "-r", "-z", "--full-tree", tree_oid, cwd=repository
    )
    if returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise GitCliError(f"git ls-tree {tree_oid} failed: {detail}")
    entries: list[TreeEntry] = []
    for record in stdout_bytes.split(b"\0"):
        if not record:
            continue
        try:
            meta, path_bytes = record.split(b"\t", 1)
            mode_b, type_b, oid_b = meta.split(b" ", 2)
        except ValueError as exc:
            raise GitCliError(f"unrecognized ls-tree record: {record!r}") from exc
        entries.append(
            TreeEntry(
                mode=mode_b.decode("ascii"),
                object_type=type_b.decode("ascii"),
                object_id=oid_b.decode("ascii"),
                path=os.fsdecode(path_bytes),
            )
        )
    return tuple(entries)


def _parse_cat_file_batch(payload: bytes) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    cursor = 0
    length = len(payload)
    while cursor < length:
        newline = payload.find(b"\n", cursor)
        if newline < 0:
            raise GitCliError("truncated git cat-file --batch header")
        header = payload[cursor:newline]
        cursor = newline + 1
        parts = header.split()
        if len(parts) == 2 and parts[1] == b"missing":
            missing_oid = parts[0].decode("ascii")
            raise GitCliError(f"missing git object {missing_oid}")
        if len(parts) != 3:
            raise GitCliError(f"unrecognized cat-file --batch header: {header!r}")
        object_id = parts[0].decode("ascii")
        size = int(parts[2])
        content = payload[cursor : cursor + size]
        if len(content) != size:
            raise GitCliError(f"truncated git cat-file --batch payload for {object_id}")
        cursor += size
        if cursor >= length or payload[cursor : cursor + 1] != b"\n":
            raise GitCliError(f"missing trailing newline in cat-file --batch for {object_id}")
        cursor += 1
        blobs[object_id] = content
    return blobs


async def cat_file_batch(object_ids: tuple[str, ...], repository: Path) -> dict[str, bytes]:
    unique_ids = tuple(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    stdin = "".join(f"{object_id}\n" for object_id in unique_ids).encode("ascii")
    returncode, stdout_bytes, stderr_bytes = await invoke_git_bytes(
        "cat-file", "--batch", cwd=repository, stdin=stdin
    )
    if returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise GitCliError(f"git cat-file --batch failed: {detail}")
    blobs = _parse_cat_file_batch(stdout_bytes)
    missing = [object_id for object_id in unique_ids if object_id not in blobs]
    if missing:
        raise GitCliError(f"git cat-file --batch omitted objects: {', '.join(missing)}")
    return blobs


_WORKTREE_SNAPSHOT_COMMIT_MESSAGE = "Worktree Review working tree snapshot"
_WORKTREE_SNAPSHOT_AUTHOR_NAME = "Worktree Review"
_WORKTREE_SNAPSHOT_AUTHOR_EMAIL = "worktree-review@localhost"
_WORKTREE_SNAPSHOT_DATE = "Thu, 1 Jan 1970 00:00:00 +0000"
_HIDDEN_INDEX_STATUS_BYTES = frozenset({b"h", b"S"})
_SKIP_WORKTREE_INDEX_STATUS_BYTE = b"S"


@dataclass(frozen=True)
class _HiddenIndexEntry:
    relative_path: str
    status_byte: bytes


@dataclass(frozen=True)
class _WorkingTreeChangeSet:
    changed_paths: tuple[str, ...]
    skip_worktree_paths: frozenset[str]


def _escaped_git_path_for_error(relative_path: str) -> str:
    """Render a repository path without allowing terminal control sequences."""

    return ascii(relative_path)


async def _git_nul_paths(*args: str, repository: Path) -> tuple[str, ...]:
    returncode, stdout_bytes, stderr_bytes = await invoke_git_bytes(
        *args,
        "-z",
        cwd=repository,
    )
    if returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        command = " ".join(("git", *args))
        raise GitCliError(f"{command} failed (exit {returncode}): {detail}")
    return tuple(os.fsdecode(path_bytes) for path_bytes in stdout_bytes.split(b"\0") if path_bytes)


async def _git_index_hidden_entries(repository: Path) -> tuple[_HiddenIndexEntry, ...]:
    """List tracked paths whose index flags can hide filesystem changes."""

    returncode, stdout_bytes, stderr_bytes = await invoke_git_bytes(
        "ls-files",
        "-v",
        "-z",
        cwd=repository,
    )
    if returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise GitCliError(f"git ls-files -v failed (exit {returncode}): {detail}")

    hidden_entries: list[_HiddenIndexEntry] = []
    for record in stdout_bytes.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] not in (b" ", b"\t"):
            raise GitCliError(f"unrecognized git ls-files -v record: {record!r}")
        if record[:1] in _HIDDEN_INDEX_STATUS_BYTES:
            hidden_entries.append(
                _HiddenIndexEntry(
                    relative_path=os.fsdecode(record[2:]),
                    status_byte=record[:1],
                )
            )
    return tuple(hidden_entries)


async def _git_working_tree_changes(repository: Path) -> _WorkingTreeChangeSet:
    unmerged_paths = await _git_nul_paths("ls-files", "-u", repository=repository)
    if unmerged_paths:
        escaped_paths = ", ".join(_escaped_git_path_for_error(path) for path in unmerged_paths)
        raise GitCliError(
            "cannot snapshot a worktree with unresolved merge entries: " + escaped_paths
        )
    hidden_index_entries = await _git_index_hidden_entries(repository)
    changed_paths = {
        *await _git_nul_paths(
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            repository=repository,
        ),
        *await _git_nul_paths(
            "diff",
            "--cached",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            repository=repository,
        ),
        *await _git_nul_paths(
            "ls-files",
            "--others",
            "--exclude-standard",
            repository=repository,
        ),
        *(entry.relative_path for entry in hidden_index_entries),
    }
    return _WorkingTreeChangeSet(
        changed_paths=tuple(sorted(changed_paths)),
        skip_worktree_paths=frozenset(
            entry.relative_path
            for entry in hidden_index_entries
            if entry.status_byte == _SKIP_WORKTREE_INDEX_STATUS_BYTE
        ),
    )


async def _git_working_tree_changed_paths(repository: Path) -> tuple[str, ...]:
    return (await _git_working_tree_changes(repository)).changed_paths


def _safe_git_working_tree_path(repository: Path, relative_path: str) -> Path:
    normalized_relative_path = relative_path.rstrip("/")
    path_parts = tuple(normalized_relative_path.split("/"))
    if not path_parts or any(part in ("", ".", "..") for part in path_parts):
        raise GitCliError(
            f"cannot snapshot unsafe Git path: {_escaped_git_path_for_error(relative_path)}"
        )
    current = repository
    for path_part in path_parts[:-1]:
        current /= path_part
        try:
            status = current.lstat()
        except FileNotFoundError:
            break
        except NotADirectoryError:
            break
        except OSError as exc:
            raise GitCliError(
                f"cannot inspect worktree path {_escaped_git_path_for_error(relative_path)}: {exc}"
            ) from exc
        if stat.S_ISLNK(status.st_mode):
            raise GitCliError(
                f"cannot snapshot {_escaped_git_path_for_error(relative_path)}: "
                "a parent directory is a symlink"
            )
        if not stat.S_ISDIR(status.st_mode):
            break
    return repository.joinpath(*path_parts)


def _git_working_tree_entry_exists(repository: Path, relative_path: str) -> bool:
    working_tree_path = _safe_git_working_tree_path(repository, relative_path)
    try:
        working_tree_path.lstat()
    except FileNotFoundError:
        return False
    except NotADirectoryError:
        return False
    except OSError as exc:
        raise GitCliError(
            f"cannot inspect worktree path {_escaped_git_path_for_error(relative_path)}: {exc}"
        ) from exc
    return True


async def _git_working_tree_blob_oid(
    repository: Path,
    relative_path: str,
    working_tree_path: Path,
    *,
    environment_overrides: Mapping[str, str],
) -> tuple[str, str]:
    try:
        status = os.lstat(working_tree_path)
    except FileNotFoundError:
        return "", ""
    except NotADirectoryError:
        return "", ""
    except OSError as exc:
        raise GitCliError(
            f"cannot inspect worktree path {_escaped_git_path_for_error(relative_path)}: {exc}"
        ) from exc

    if stat.S_ISLNK(status.st_mode):
        try:
            link_target = os.fsencode(os.readlink(working_tree_path))
        except OSError as exc:
            raise GitCliError(
                f"cannot read symlink {_escaped_git_path_for_error(relative_path)}: {exc}"
            ) from exc
        return (
            await _hash_git_working_tree_bytes(
                repository,
                link_target,
                environment_overrides=environment_overrides,
            ),
            "120000",
        )
    if stat.S_ISREG(status.st_mode):
        blob_oid = (
            await run_git(
                "hash-object",
                "-w",
                "--no-filters",
                "--",
                relative_path,
                cwd=repository,
                environment_overrides=environment_overrides,
            )
        ).strip()
        if not blob_oid:
            raise GitCliError(
                "git hash-object returned no object for "
                f"{_escaped_git_path_for_error(relative_path)}"
            )
        mode = "100755" if status.st_mode & stat.S_IXUSR else "100644"
        return blob_oid, mode
    if stat.S_ISDIR(status.st_mode):
        nested_git_metadata = working_tree_path / ".git"
        try:
            nested_git_status = nested_git_metadata.lstat()
        except FileNotFoundError:
            return "", ""
        except OSError as exc:
            raise GitCliError(
                "cannot inspect nested Git metadata for "
                f"{_escaped_git_path_for_error(relative_path)}: {exc}"
            ) from exc
        if (
            stat.S_ISDIR(nested_git_status.st_mode)
            or stat.S_ISREG(nested_git_status.st_mode)
            or stat.S_ISLNK(nested_git_status.st_mode)
        ):
            raise GitCliError(
                "cannot snapshot "
                f"{_escaped_git_path_for_error(relative_path)}: nested Git repositories are not "
                "representable in the outer Git tree"
            )
        return "", ""
    raise GitCliError(
        f"cannot snapshot {_escaped_git_path_for_error(relative_path)}: "
        "unsupported worktree entry type"
    )


async def _hash_git_working_tree_bytes(
    repository: Path,
    data: bytes,
    *,
    environment_overrides: Mapping[str, str],
) -> str:
    returncode, stdout_bytes, stderr_bytes = await invoke_git_bytes(
        "hash-object",
        "-w",
        "--no-filters",
        "--stdin",
        cwd=repository,
        stdin=data,
        environment_overrides=environment_overrides,
    )
    if returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise GitCliError(f"git hash-object failed (exit {returncode}): {detail}")
    blob_oid = stdout_bytes.decode("ascii", errors="replace").strip()
    if not blob_oid:
        raise GitCliError("git hash-object returned no object for a worktree symlink")
    return blob_oid


def _affected_baseline_paths(
    baseline_entries: dict[str, TreeEntry],
    changed_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Find baseline entries touched by a path or file/directory replacement.

    The indexes make the lookup proportional to path depth plus the number of
    affected entries instead of comparing every baseline path with every change.
    """

    baseline_paths = set(baseline_entries)
    baseline_descendants_by_directory: dict[str, set[str]] = {}
    for baseline_path in baseline_paths:
        baseline_path_parts = baseline_path.split("/")
        for ancestor_length in range(1, len(baseline_path_parts)):
            ancestor_directory = "/".join(baseline_path_parts[:ancestor_length])
            baseline_descendants_by_directory.setdefault(ancestor_directory, set()).add(
                baseline_path
            )

    affected_paths: set[str] = set()
    for changed_path in changed_paths:
        normalized_changed_path = changed_path.rstrip("/")
        affected_paths.update(baseline_descendants_by_directory.get(normalized_changed_path, ()))
        changed_path_parts = normalized_changed_path.split("/")
        for ancestor_length in range(1, len(changed_path_parts) + 1):
            possible_baseline_path = "/".join(changed_path_parts[:ancestor_length])
            if possible_baseline_path in baseline_paths:
                affected_paths.add(possible_baseline_path)
    return tuple(sorted(affected_paths))


async def snapshot_git_working_tree_as_commit(repository: Path, parent_commit: str) -> str:
    """Capture the visible worktree as an unreachable, immutable Git commit.

    The normal index and worktree are never changed. Tracked files use their current
    filesystem bytes, non-ignored untracked files are included, ignored files are
    excluded, and Git filters are disabled while hashing repository content.
    """

    worktree_changes = await _git_working_tree_changes(repository)
    changed_paths = tuple(
        relative_path
        for relative_path in worktree_changes.changed_paths
        if relative_path not in worktree_changes.skip_worktree_paths
        or _git_working_tree_entry_exists(repository, relative_path)
    )
    if not changed_paths:
        return parent_commit

    baseline_entries = {
        entry.path: entry for entry in await list_tree_entries(parent_commit, repository)
    }
    environment_overrides: dict[str, str]
    with tempfile.TemporaryDirectory(prefix="worktree-review-index-") as index_directory:
        environment_overrides = {"GIT_INDEX_FILE": str(Path(index_directory) / "index")}
        await run_git(
            "read-tree",
            parent_commit,
            cwd=repository,
            environment_overrides=environment_overrides,
        )
        affected_baseline_paths = _affected_baseline_paths(baseline_entries, changed_paths)
        for baseline_path in affected_baseline_paths:
            await run_git(
                "update-index",
                "--force-remove",
                "--",
                baseline_path,
                cwd=repository,
                environment_overrides=environment_overrides,
            )
        for relative_path in changed_paths:
            baseline_entry = baseline_entries.get(relative_path)
            if baseline_entry is not None and baseline_entry.mode == "160000":
                raise GitCliError(
                    "cannot snapshot changed submodule path "
                    f"{_escaped_git_path_for_error(relative_path)}"
                )
            working_tree_path = _safe_git_working_tree_path(repository, relative_path)
            blob_oid, mode = await _git_working_tree_blob_oid(
                repository,
                relative_path,
                working_tree_path,
                environment_overrides=environment_overrides,
            )
            if not blob_oid:
                continue
            await run_git(
                "update-index",
                "--add",
                "--cacheinfo",
                f"{mode},{blob_oid},{relative_path}",
                cwd=repository,
                environment_overrides=environment_overrides,
            )
        tree_oid = (
            await run_git(
                "write-tree",
                cwd=repository,
                environment_overrides=environment_overrides,
            )
        ).strip()
        parent_tree_oid = await commit_tree_oid(parent_commit, repository)
        if tree_oid == parent_tree_oid:
            return parent_commit
        snapshot_commit = (
            await run_git(
                "commit-tree",
                tree_oid,
                "-p",
                parent_commit,
                "-m",
                _WORKTREE_SNAPSHOT_COMMIT_MESSAGE,
                cwd=repository,
                environment_overrides={
                    **environment_overrides,
                    "GIT_AUTHOR_NAME": _WORKTREE_SNAPSHOT_AUTHOR_NAME,
                    "GIT_AUTHOR_EMAIL": _WORKTREE_SNAPSHOT_AUTHOR_EMAIL,
                    "GIT_COMMITTER_NAME": _WORKTREE_SNAPSHOT_AUTHOR_NAME,
                    "GIT_COMMITTER_EMAIL": _WORKTREE_SNAPSHOT_AUTHOR_EMAIL,
                    "GIT_AUTHOR_DATE": _WORKTREE_SNAPSHOT_DATE,
                    "GIT_COMMITTER_DATE": _WORKTREE_SNAPSHOT_DATE,
                },
            )
        ).strip()
    if not snapshot_commit:
        raise GitCliError("git commit-tree returned no worktree snapshot commit")
    return snapshot_commit
