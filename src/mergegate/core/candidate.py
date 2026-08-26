"""Merge-candidate construction via ``git merge-tree --write-tree`` (TECH-DESIGN D2)."""

from __future__ import annotations

import re
from pathlib import Path

from mergegate.core.errors import MergeConflictError, MergeConstructionError
from mergegate.core.git import invoke_git
from mergegate.core.identity import MergeCandidateIdentity, ResolvedCommitPair

_TREE_OID_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")


def _repository_path(resolved: ResolvedCommitPair) -> Path:
    return Path(resolved.source_repository)


def _parse_tree_oid(first_line: str) -> str:
    oid = first_line.strip()
    if not _TREE_OID_PATTERN.fullmatch(oid):
        raise MergeConstructionError(f"git merge-tree did not print a tree OID: {first_line!r}")
    return oid


def _conflicted_paths(merge_tree_stdout: str) -> tuple[str, ...]:
    """``--name-only`` prints the tree OID, then conflicted paths, then a blank line."""

    lines = merge_tree_stdout.splitlines()
    paths: list[str] = []
    for line in lines[1:]:
        if line == "":
            break
        paths.append(line)
    return tuple(paths)


async def construct_merge_candidate(resolved: ResolvedCommitPair) -> MergeCandidateIdentity:
    """Merge proposed head into target head in the object database. No checkout.

    Fail closed on conflict (PRD §8.1): a conflicted tree is never the merge
    candidate. Unrelated histories and missing objects are construction errors.
    """

    repository = _repository_path(resolved)
    if not repository.is_dir():
        raise MergeConstructionError(f"source repository does not exist: {repository}")

    result = await invoke_git(
        "merge-tree",
        "--write-tree",
        "--name-only",
        resolved.target_head_oid,
        resolved.proposed_head_oid,
        cwd=repository,
    )
    stdout_lines = result.stdout.splitlines()
    first_line = stdout_lines[0].strip() if stdout_lines else ""
    if result.returncode == 0:
        merge_tree_oid = _parse_tree_oid(first_line)
        return MergeCandidateIdentity(
            source_repository=resolved.source_repository,
            target_ref=resolved.target_ref,
            target_head_oid=resolved.target_head_oid,
            proposed_head_oid=resolved.proposed_head_oid,
            merge_tree_oid=merge_tree_oid,
        )
    # Conflicted merges still print a tree OID first (do not use it). Git also uses
    # exit 1 for "not something we can merge"; that path has no tree OID on stdout.
    if result.returncode == 1 and _TREE_OID_PATTERN.fullmatch(first_line):
        paths = _conflicted_paths(result.stdout)
        listed = ", ".join(paths) if paths else "(see git merge-tree output)"
        raise MergeConflictError(
            "merge conflict constructing the merge candidate; refusing to review a "
            f"conflicted tree (paths: {listed})",
            conflicted_paths=paths,
        )
    detail = result.stderr.strip() or result.stdout.strip()
    raise MergeConstructionError(
        f"git merge-tree --write-tree could not complete (exit {result.returncode}): {detail}"
    )
