"""System git CLI wrapper. Merge fidelity requires git ≥ 2.38 (TECH-DESIGN D2)."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

from mergegate.core.errors import (
    GitRequiredError,
    InvalidInvocationError,
    MergeGateError,
)

MIN_GIT_VERSION: tuple[int, int, int] = (2, 38, 0)
_VERSION_PATTERN = re.compile(r"git version (\d+)\.(\d+)\.(\d+)")
_HOOKS_DISABLED: tuple[str, ...] = ("-c", "core.hooksPath=/dev/null")


class GitCliError(MergeGateError):
    """A git subprocess failed. Callers decide whether that is invocation or review Error."""


@dataclass(frozen=True)
class GitProcessResult:
    returncode: int
    stdout: str
    stderr: str


def isolated_git_env() -> dict[str, str]:
    """Minimal env: no user gitconfig, no hooks, no provider/platform tokens."""

    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def parse_git_version(version_stdout: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.search(version_stdout)
    if match is None:
        raise GitRequiredError(f"unrecognized git version output: {version_stdout!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


async def invoke_git(*args: str, cwd: Path) -> GitProcessResult:
    process = await asyncio.create_subprocess_exec(
        "git",
        *_HOOKS_DISABLED,
        *args,
        cwd=cwd,
        env=isolated_git_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    return GitProcessResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


async def run_git(*args: str, cwd: Path) -> str:
    result = await invoke_git(*args, cwd=cwd)
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
        raise GitRequiredError(f"git {pretty} is too old; MergeGate requires git >= {required}")
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
    *args: str, cwd: Path, stdin: bytes | None = None
) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        "git",
        *_HOOKS_DISABLED,
        *args,
        cwd=cwd,
        env=isolated_git_env(),
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
