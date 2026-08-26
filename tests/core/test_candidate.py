from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import checkout_new_branch, commit_files, git, head_oid

from mergegate.core.candidate import construct_merge_candidate
from mergegate.core.errors import MergeConflictError, MergeConstructionError
from mergegate.core.git import worktree_is_clean
from mergegate.core.identity import ResolvedCommitPair


def _pair(repository: Path, target_oid: str, proposed_oid: str) -> ResolvedCommitPair:
    return ResolvedCommitPair(
        source_repository=str(repository),
        target_ref="main",
        target_head_oid=target_oid,
        proposed_ref="HEAD",
        proposed_head_oid=proposed_oid,
    )


@pytest.mark.asyncio
async def test_self_merge_returns_commit_tree(git_repository: Path) -> None:
    oid = head_oid(git_repository)
    tree = git(git_repository, "rev-parse", f"{oid}^{{tree}}").strip()
    candidate = await construct_merge_candidate(_pair(git_repository, oid, oid))
    assert candidate.merge_tree_oid == tree
    assert await worktree_is_clean(git_repository)


@pytest.mark.asyncio
async def test_clean_add_on_proposed_head(git_repository: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(git_repository, {"extra.txt": "added\n"}, "add extra")
    git(git_repository, "checkout", "main")
    candidate = await construct_merge_candidate(_pair(git_repository, target_oid, proposed_oid))
    listed = git(git_repository, "ls-tree", "-r", "--name-only", candidate.merge_tree_oid)
    assert "extra.txt" in listed.splitlines()
    assert "README" in listed.splitlines()
    assert await worktree_is_clean(git_repository)


@pytest.mark.asyncio
async def test_conflict_is_fail_closed_and_does_not_dirty_worktree(git_repository: Path) -> None:
    commit_files(git_repository, {"file.txt": "base\n"}, "base")
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(git_repository, {"file.txt": "topic\n"}, "topic")
    git(git_repository, "checkout", "main")
    target_oid = commit_files(git_repository, {"file.txt": "main\n"}, "main")
    with pytest.raises(MergeConflictError) as captured:
        await construct_merge_candidate(_pair(git_repository, target_oid, proposed_oid))
    assert "file.txt" in captured.value.conflicted_paths
    assert await worktree_is_clean(git_repository)


@pytest.mark.asyncio
async def test_rename_on_proposed_side_is_clean(git_repository: Path) -> None:
    commit_files(git_repository, {"old.txt": "hello\n"}, "add old")
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "rename")
    git(git_repository, "mv", "old.txt", "new.txt")
    git(git_repository, "commit", "-m", "rename old to new")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
    candidate = await construct_merge_candidate(_pair(git_repository, target_oid, proposed_oid))
    names = git(git_repository, "ls-tree", "-r", "--name-only", candidate.merge_tree_oid)
    assert "new.txt" in names.splitlines()
    assert "old.txt" not in names.splitlines()


@pytest.mark.asyncio
async def test_missing_objects_fail_closed(git_repository: Path) -> None:
    with pytest.raises(MergeConstructionError, match="could not complete"):
        await construct_merge_candidate(
            _pair(git_repository, "no-such-target-object", "no-such-proposed-object")
        )


@pytest.mark.asyncio
async def test_unrelated_histories_fail_closed(git_repository: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-b", "other")
    git(other, "config", "user.email", "mergegate-test@example.com")
    git(other, "config", "user.name", "MergeGate Test")
    commit_files(other, {"x.txt": "x\n"}, "unrelated")
    git(git_repository, "remote", "add", "other", str(other))
    git(git_repository, "fetch", "other")
    other_oid = git(git_repository, "rev-parse", "other/other").strip()
    target_oid = head_oid(git_repository)
    with pytest.raises(MergeConstructionError, match="unrelated"):
        await construct_merge_candidate(_pair(git_repository, target_oid, other_oid))
