from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import checkout_new_branch, commit_files, git, head_oid

from mergegate.core.candidate import construct_merge_candidate
from mergegate.core.errors import WorkspaceError
from mergegate.core.identity import MergeCandidateIdentity, ResolvedCommitPair
from mergegate.core.workspace import (
    TREE_DIRECTORY_NAME,
    WORKSPACE_MARKER_NAME,
    ReviewWorkspace,
    assert_acceptable_workspace_destination,
    cleanup_review_workspace,
    materialize_read_only_workspace,
)


@pytest.mark.asyncio
async def test_workspace_is_read_only_and_contains_tree(
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
    destination = tmp_path / "mergegate-ws-test"
    workspace = await materialize_read_only_workspace(candidate, destination=destination)
    readme = workspace.root / "README"
    assert readme.read_text(encoding="utf-8") == "hello\n"
    with pytest.raises(PermissionError):
        readme.write_text("mutated\n", encoding="utf-8")
    await cleanup_review_workspace(workspace)
    assert not destination.exists()


@pytest.mark.asyncio
async def test_cleanup_refuses_unmarked_directory(tmp_path: Path) -> None:
    unmarked = tmp_path / "not-a-workspace"
    unmarked.mkdir()
    (unmarked / "file").write_text("keep\n", encoding="utf-8")
    workspace = ReviewWorkspace(
        root=unmarked / "tree",
        container_root=unmarked,
        merge_tree_oid="a" * 40,
        owner_note="test",
    )
    with pytest.raises(WorkspaceError, match="missing"):
        await cleanup_review_workspace(workspace)
    assert (unmarked / "file").read_text(encoding="utf-8") == "keep\n"


def test_refuses_home_as_workspace() -> None:
    with pytest.raises(WorkspaceError, match=r"protected|home"):
        assert_acceptable_workspace_destination(Path.home())


@pytest.mark.asyncio
async def test_nonempty_destination_is_rejected(git_repository: Path, tmp_path: Path) -> None:
    oid = head_oid(git_repository)
    candidate = MergeCandidateIdentity(
        source_repository=str(git_repository),
        target_ref="main",
        target_head_oid=oid,
        proposed_head_oid=oid,
        merge_tree_oid=oid,  # not a tree; we fail before archive if dest nonempty
    )
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "already").write_text("nope\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not empty"):
        await materialize_read_only_workspace(candidate, destination=dest)


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
    workspace = await materialize_read_only_workspace(
        candidate, destination=tmp_path / "mergegate-ws-export"
    )
    try:
        assert (workspace.root / "secret.txt").read_text(encoding="utf-8") == "classified\n"
        assert (workspace.container_root / TREE_DIRECTORY_NAME) == workspace.root
    finally:
        await cleanup_review_workspace(workspace)


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
    workspace = await materialize_read_only_workspace(
        candidate, destination=tmp_path / "mergegate-ws-subst"
    )
    try:
        assert (workspace.root / "subst.txt").read_text(encoding="utf-8") == "id $Format:%H$\n"
    finally:
        await cleanup_review_workspace(workspace)


@pytest.mark.asyncio
async def test_repo_marker_symlink_does_not_overwrite_external_file(
    git_repository: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    link = git_repository / WORKSPACE_MARKER_NAME
    link.symlink_to(victim)
    git(git_repository, "add", "-f", WORKSPACE_MARKER_NAME)
    git(git_repository, "commit", "-m", "add marker symlink")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
    candidate = await _candidate_for_heads(git_repository, target_oid, proposed_oid)
    workspace = await materialize_read_only_workspace(
        candidate, destination=tmp_path / "mergegate-ws-marker"
    )
    try:
        assert victim.read_text(encoding="utf-8") == "untouched\n"
        marker = workspace.container_root / WORKSPACE_MARKER_NAME
        assert marker.is_file()
        assert not marker.is_symlink()
        assert marker.read_text(encoding="utf-8") == candidate.merge_tree_oid + "\n"
        planted = workspace.root / WORKSPACE_MARKER_NAME
        assert planted.is_symlink()
        assert planted.readlink() == victim
    finally:
        await cleanup_review_workspace(workspace)
    assert victim.read_text(encoding="utf-8") == "untouched\n"
