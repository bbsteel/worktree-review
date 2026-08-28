from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import checkout_new_branch, commit_files, git, head_oid

from worktree_review.core.candidate import construct_merge_candidate
from worktree_review.core.context import (
    MERGE_CANDIDATE_DIFF_PATH,
    ContextClass,
    gather_context,
    path_matches_glob,
    unreviewable_reason,
)
from worktree_review.core.findings import EvidenceSource
from worktree_review.core.identity import ResolvedCommitPair
from worktree_review.core.policy import ReviewPolicy
from worktree_review.core.review_worktree import (
    cleanup_review_worktree,
    materialize_review_worktree,
)


def _policy(**context: object) -> ReviewPolicy:
    payload: dict[str, object] = {
        "schema": "worktree-review.review-policy/v1",
        "version": "1.0.0",
        "required_dimensions": ["correctness"],
        "context": {"optional_globs": [], **context},
    }
    return ReviewPolicy.model_validate(payload)


def _pair(repository: Path, target_oid: str, proposed_oid: str) -> ResolvedCommitPair:
    return ResolvedCommitPair(
        source_repository=str(repository),
        target_ref="main",
        target_head_oid=target_oid,
        proposed_ref="HEAD",
        proposed_head_oid=proposed_oid,
    )


async def _gather(
    repository: Path,
    policy: ReviewPolicy,
    target_oid: str,
    proposed_oid: str,
    tmp_path: Path,
):
    candidate = await construct_merge_candidate(_pair(repository, target_oid, proposed_oid))
    review_worktree = await materialize_review_worktree(
        candidate, destination=tmp_path / "worktree-review-ctx"
    )
    try:
        return await gather_context(review_worktree, candidate, policy)
    finally:
        await cleanup_review_worktree(review_worktree)


def test_path_glob_matching() -> None:
    assert path_matches_glob("foo.png", "*.png")
    assert path_matches_glob("dir/foo.png", "*.png")
    assert path_matches_glob("vendor/pkg/a.py", "vendor/**")
    assert not path_matches_glob("src/a.py", "vendor/**")
    assert path_matches_glob("AGENTS.md", "AGENTS.md")
    assert path_matches_glob("nested/AGENTS.md", "AGENTS.md")
    assert path_matches_glob(".env", ".env")
    assert path_matches_glob("./.env", ".env")
    assert path_matches_glob(".github/workflows/ci.yml", ".github/**")
    assert not path_matches_glob(".env", "env")


def test_unreviewable_reasons() -> None:
    assert unreviewable_reason(b"ok\n", max_file_bytes=100) is None
    assert unreviewable_reason(b"\x00bin", max_file_bytes=100) == "binary (NUL byte)"
    assert unreviewable_reason(b"abcd", max_file_bytes=2) is not None
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:ab\nsize 1\n"
    assert unreviewable_reason(pointer, max_file_bytes=10_000) == "git-lfs pointer"


@pytest.mark.asyncio
async def test_identical_heads_have_complete_empty_change_coverage(
    git_repository: Path, tmp_path: Path
) -> None:
    oid = head_oid(git_repository)
    gathered = await _gather(git_repository, _policy(), oid, oid, tmp_path)
    assert gathered.coverage.required_coverage_complete is True
    assert MERGE_CANDIDATE_DIFF_PATH in gathered.coverage.reviewed
    assert gathered.coverage.unreviewable == ()


@pytest.mark.asyncio
async def test_changed_text_file_is_reviewed(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(git_repository, {"src/app.py": "print(1)\n"}, "add app")
    git(git_repository, "checkout", "main")
    gathered = await _gather(git_repository, _policy(), target_oid, proposed_oid, tmp_path)
    by_path = {item.path: item for item in gathered.items}
    assert by_path["src/app.py"].context_class is ContextClass.MANDATORY
    assert by_path["src/app.py"].source is EvidenceSource.REVIEW_WORKTREE
    assert by_path["src/app.py"].snapshot_identity is not None
    assert by_path[MERGE_CANDIDATE_DIFF_PATH].source is EvidenceSource.MERGE_DIFF
    assert by_path[MERGE_CANDIDATE_DIFF_PATH].snapshot_identity is not None
    assert by_path["src/app.py"].body == "print(1)\n"
    assert "src/app.py" in gathered.coverage.reviewed
    assert gathered.coverage.required_coverage_complete is True
    assert "print(1)" in (by_path[MERGE_CANDIDATE_DIFF_PATH].body or "")
    assert "BEGIN CONTEXT" in by_path["src/app.py"].as_delimited()


@pytest.mark.asyncio
async def test_excluded_glob_is_disclosed_and_not_in_diff(
    git_repository: Path, tmp_path: Path
) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(
        git_repository,
        {"vendor/lib.py": "secret\n", "src/app.py": "print(1)\n"},
        "add vendor and app",
    )
    git(git_repository, "checkout", "main")
    gathered = await _gather(
        git_repository,
        _policy(excluded_globs=["vendor/**"]),
        target_oid,
        proposed_oid,
        tmp_path,
    )
    by_path = {item.path: item for item in gathered.items}
    assert by_path["vendor/lib.py"].context_class is ContextClass.EXCLUDED
    assert "vendor/lib.py" in gathered.coverage.excluded
    assert "secret" not in (by_path[MERGE_CANDIDATE_DIFF_PATH].body or "")
    assert "src/app.py" in gathered.coverage.reviewed
    assert gathered.coverage.required_coverage_complete is True


@pytest.mark.asyncio
async def test_binary_changed_file_is_unreviewable(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    blob = git_repository / "data.bin"
    blob.write_bytes(b"hello\x00world")
    git(git_repository, "add", "data.bin")
    git(git_repository, "commit", "-m", "add binary")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
    gathered = await _gather(git_repository, _policy(), target_oid, proposed_oid, tmp_path)
    assert gathered.coverage.required_coverage_complete is False
    assert any("data.bin" in entry for entry in gathered.coverage.unreviewable)


@pytest.mark.asyncio
async def test_excluded_binary_does_not_fail_coverage(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    blob = git_repository / "data.bin"
    blob.write_bytes(b"hello\x00world")
    git(git_repository, "add", "data.bin")
    git(git_repository, "commit", "-m", "add binary")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
    gathered = await _gather(
        git_repository,
        _policy(excluded_globs=["*.bin"]),
        target_oid,
        proposed_oid,
        tmp_path,
    )
    assert gathered.coverage.required_coverage_complete is True
    assert "data.bin" in gathered.coverage.excluded
    assert gathered.coverage.unreviewable == ()


@pytest.mark.asyncio
async def test_lfs_pointer_is_unreviewable(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(
        git_repository,
        {"assets/x.png": ("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12\n")},
        "add lfs pointer",
    )
    git(git_repository, "checkout", "main")
    gathered = await _gather(git_repository, _policy(), target_oid, proposed_oid, tmp_path)
    assert gathered.coverage.required_coverage_complete is False
    assert any("git-lfs" in entry for entry in gathered.coverage.unreviewable)


@pytest.mark.asyncio
async def test_oversized_file_is_unreviewable(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(git_repository, {"big.txt": "abcdefghij\n"}, "add big")
    git(git_repository, "checkout", "main")
    gathered = await _gather(
        git_repository,
        _policy(max_file_bytes=4),
        target_oid,
        proposed_oid,
        tmp_path,
    )
    assert gathered.coverage.required_coverage_complete is False
    assert any("big.txt" in entry for entry in gathered.coverage.unreviewable)


@pytest.mark.asyncio
async def test_optional_instruction_file_is_loaded(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(git_repository, {"AGENTS.md": "be careful\n"}, "add agents")
    git(git_repository, "checkout", "main")
    gathered = await _gather(
        git_repository,
        _policy(optional_globs=["AGENTS.md"]),
        target_oid,
        proposed_oid,
        tmp_path,
    )
    by_path = {item.path: item for item in gathered.items}
    # Changed file is mandatory in-scope, not merely optional.
    assert by_path["AGENTS.md"].context_class is ContextClass.MANDATORY
    assert by_path["AGENTS.md"].untrusted is True
    assert by_path["AGENTS.md"].body == "be careful\n"


@pytest.mark.asyncio
async def test_optional_glob_missing_is_disclosed(git_repository: Path, tmp_path: Path) -> None:
    oid = head_oid(git_repository)
    gathered = await _gather(
        git_repository,
        _policy(optional_globs=["AGENTS.md", "CLAUDE.md"]),
        oid,
        oid,
        tmp_path,
    )
    assert gathered.coverage.required_coverage_complete is True
    assert "AGENTS.md" in gathered.coverage.optional_missing
    assert "CLAUDE.md" in gathered.coverage.optional_missing


@pytest.mark.asyncio
async def test_mandatory_glob_missing_is_incomplete(git_repository: Path, tmp_path: Path) -> None:
    oid = head_oid(git_repository)
    gathered = await _gather(
        git_repository,
        _policy(mandatory_globs=["SPEC.md"]),
        oid,
        oid,
        tmp_path,
    )
    assert gathered.coverage.required_coverage_complete is False
    assert "SPEC.md" in gathered.coverage.mandatory_missing


@pytest.mark.asyncio
async def test_deleted_file_includes_target_body(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    git(git_repository, "rm", "README")
    git(git_repository, "commit", "-m", "remove readme")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
    gathered = await _gather(git_repository, _policy(), target_oid, proposed_oid, tmp_path)
    by_path = {item.path: item for item in gathered.items}
    assert by_path["README"].change_kind is not None
    assert by_path["README"].change_kind.value == "deleted"
    assert by_path["README"].source is EvidenceSource.TARGET_TREE
    assert by_path["README"].snapshot_identity is not None
    assert by_path["README"].body == "hello\n"
    assert gathered.coverage.required_coverage_complete is True


@pytest.mark.asyncio
async def test_dotfile_exclusion_glob_matches(git_repository: Path, tmp_path: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(
        git_repository,
        {".env": "SECRET=1\n", "src/app.py": "print(1)\n"},
        "add env and app",
    )
    git(git_repository, "checkout", "main")
    gathered = await _gather(
        git_repository,
        _policy(excluded_globs=[".env", ".github/**"]),
        target_oid,
        proposed_oid,
        tmp_path,
    )
    assert ".env" in gathered.coverage.excluded
    assert "SECRET=1" not in "".join(item.body or "" for item in gathered.items)
    assert "src/app.py" in gathered.coverage.reviewed


@pytest.mark.asyncio
async def test_repo_review_worktree_marker_path_is_not_skipped(
    git_repository: Path, tmp_path: Path
) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(
        git_repository,
        {".worktree-review-marker": "not-a-marker\n"},
        "add colliding marker name",
    )
    git(git_repository, "checkout", "main")
    gathered = await _gather(git_repository, _policy(), target_oid, proposed_oid, tmp_path)
    by_path = {item.path: item for item in gathered.items}
    assert ".worktree-review-marker" in by_path
    assert by_path[".worktree-review-marker"].body == "not-a-marker\n"
