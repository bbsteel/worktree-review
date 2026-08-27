from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import checkout_new_branch, commit_files, git, head_oid

from worktree_review.core.candidate import construct_merge_candidate
from worktree_review.core.errors import ReviewWorktreeError
from worktree_review.core.identity import MergeCandidateIdentity, ResolvedCommitPair
from worktree_review.core.review_worktree import (
    REVIEW_TREE_DIRECTORY_NAME,
    REVIEW_WORKTREE_MARKER_NAME,
    ReviewWorktree,
    assert_acceptable_review_worktree_destination,
    cleanup_review_worktree,
    materialize_review_worktree,
)


@pytest.mark.asyncio
async def test_review_worktree_is_read_only_and_contains_tree(
    git_repository: Path, tmp_path: Path
) -> None:
    oid = head_oid(git_repository)
    candidate = await construct_merge_candidate(
        ResolvedCommitPair(
            source_repository=str(git_repository),
            target_ref="main",
            target_head_oid=oid,
            proposed_ref="HEAD",
            proposed_head_oid=oid,
        )
    )
    destination = tmp_path / "worktree-review-test"
    review_worktree = await materialize_review_worktree(candidate, destination=destination)
    readme = review_worktree.root / "README"
    assert readme.read_text(encoding="utf-8") == "hello\n"
    with pytest.raises(PermissionError):
        readme.write_text("mutated\n", encoding="utf-8")
    await cleanup_review_worktree(review_worktree)
    assert not destination.exists()


@pytest.mark.asyncio
async def test_cleanup_refuses_unmarked_directory(tmp_path: Path) -> None:
    unmarked = tmp_path / "not-a-review-worktree"
    unmarked.mkdir()
    (unmarked / "file").write_text("keep\n", encoding="utf-8")
    review_worktree = ReviewWorktree(
        root=unmarked / "tree",
        container_root=unmarked,
        merge_tree_oid="a" * 40,
        owner_note="test",
    )
    with pytest.raises(ReviewWorktreeError, match="missing"):
        await cleanup_review_worktree(review_worktree)
    assert (unmarked / "file").read_text(encoding="utf-8") == "keep\n"


def test_refuses_home_as_review_worktree() -> None:
    with pytest.raises(ReviewWorktreeError, match=r"protected|home"):
        assert_acceptable_review_worktree_destination(Path.home())


@pytest.mark.asyncio
async def test_nonempty_destination_is_rejected(git_repository: Path, tmp_path: Path) -> None:
    oid = head_oid(git_repository)
    candidate = MergeCandidateIdentity(
        source_repository=str(git_repository),
        target_ref="main",
        target_head_oid=oid,
        proposed_head_oid=oid,
        merge_tree_oid=oid,  # not a tree; we fail before materialize if dest nonempty
    )
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "already").write_text("nope\n", encoding="utf-8")
    with pytest.raises(ReviewWorktreeError, match="not empty"):
        await materialize_review_worktree(candidate, destination=dest)


def _candidate_for_heads(repository: Path, target_oid: str, proposed_oid: str):
    return construct_merge_candidate(
        ResolvedCommitPair(
            source_repository=str(repository),
            target_ref="main",
            target_head_oid=target_oid,
            proposed_ref="HEAD",
            proposed_head_oid=proposed_oid,
        )
    )


@pytest.mark.asyncio
async def test_export_ignore_does_not_omit_tree_content(
    git_repository: Path, tmp_path: Path
) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(
        git_repository,
        {
            ".gitattributes": "secret.txt export-ignore\n",
            "secret.txt": "classified\n",
        },
        "add export-ignore secret",
    )
    git(git_repository, "checkout", "main")
    candidate = await _candidate_for_heads(git_repository, target_oid, proposed_oid)
    review_worktree = await materialize_review_worktree(
        candidate, destination=tmp_path / "worktree-review-export"
    )
    try:
        assert (review_worktree.root / "secret.txt").read_text(encoding="utf-8") == "classified\n"
        assert (review_worktree.container_root / REVIEW_TREE_DIRECTORY_NAME) == review_worktree.root
    finally:
        await cleanup_review_worktree(review_worktree)


@pytest.mark.asyncio
async def test_export_subst_does_not_rewrite_blob_content(
    git_repository: Path, tmp_path: Path
) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(
        git_repository,
        {
            ".gitattributes": "subst.txt export-subst\n",
            "subst.txt": "id $Format:%H$\n",
        },
        "add export-subst file",
    )
    git(git_repository, "checkout", "main")
    candidate = await _candidate_for_heads(git_repository, target_oid, proposed_oid)
    review_worktree = await materialize_review_worktree(
        candidate, destination=tmp_path / "worktree-review-subst"
    )
    try:
        assert (review_worktree.root / "subst.txt").read_text(encoding="utf-8") == (
            "id $Format:%H$\n"
        )
    finally:
        await cleanup_review_worktree(review_worktree)


@pytest.mark.asyncio
async def test_repo_marker_symlink_does_not_overwrite_external_file(
    git_repository: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    link = git_repository / REVIEW_WORKTREE_MARKER_NAME
    link.symlink_to(victim)
    git(git_repository, "add", "-f", REVIEW_WORKTREE_MARKER_NAME)
    git(git_repository, "commit", "-m", "add marker symlink")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
    candidate = await _candidate_for_heads(git_repository, target_oid, proposed_oid)
    review_worktree = await materialize_review_worktree(
        candidate, destination=tmp_path / "worktree-review-marker"
    )
    try:
        assert victim.read_text(encoding="utf-8") == "untouched\n"
        marker = review_worktree.container_root / REVIEW_WORKTREE_MARKER_NAME
        assert marker.is_file()
        assert not marker.is_symlink()
        assert marker.read_text(encoding="utf-8") == candidate.merge_tree_oid + "\n"
        planted = review_worktree.root / REVIEW_WORKTREE_MARKER_NAME
        assert planted.is_symlink()
        assert planted.readlink() == victim
    finally:
        await cleanup_review_worktree(review_worktree)
    assert victim.read_text(encoding="utf-8") == "untouched\n"
