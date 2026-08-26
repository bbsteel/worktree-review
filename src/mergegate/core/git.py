"""System git CLI wrapper. Merge fidelity requires git ≥ 2.38 (TECH-DESIGN D2)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from mergegate.core.errors import (
    GitRequiredError,
    InvalidInvocationError,
    MergeGateError,
)

MIN_GIT_VERSION: tuple[int, int, int] = (2, 38, 0)
_VERSION_PATTERN = re.compile(r"git version (\d+)\.(\d+)\.(\d+)")


class GitCliError(MergeGateError):
    """A git subprocess failed. Callers decide whether that is invocation or review Error."""


def parse_git_version(version_stdout: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.search(version_stdout)
    if match is None:
        raise GitRequiredError(f"unrecognized git version output: {version_stdout!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


async def run_git(*args: str, cwd: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if process.returncode != 0:
        joined = " ".join(("git", *args))
        raise GitCliError(
            f"{joined} failed (exit {process.returncode}): {stderr.strip() or stdout.strip()}"
        )
    return stdout


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
