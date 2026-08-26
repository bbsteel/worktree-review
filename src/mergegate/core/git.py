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

    process = await asyncio.create_subprocess_exec(
        "git",
        *_HOOKS_DISABLED,
        "cat-file",
        "-p",
        spec,
        cwd=repository,
        env=isolated_git_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    if process.returncode != 0:
        detail = stderr_bytes.decode("utf-8", errors="replace").strip()
        raise GitCliError(f"git cat-file -p {spec} failed: {detail}")
    return stdout_bytes
