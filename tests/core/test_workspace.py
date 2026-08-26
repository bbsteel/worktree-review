from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import head_oid

from mergegate.core.candidate import construct_merge_candidate
from mergegate.core.errors import WorkspaceError
from mergegate.core.identity import MergeCandidateIdentity, ResolvedCommitPair
from mergegate.core.workspace import (
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
        root=unmarked,
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
