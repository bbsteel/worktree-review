from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import checkout_new_branch, commit_files, git, head_oid

from mergegate.core.identity import ResolvedCommitPair
from mergegate.core.pipeline import ReviewRequest, run_review_pipeline
from mergegate.core.policy import load_compute_policy, load_review_policy
from mergegate.core.report import (
    PIPELINE_STAGE_ORDER,
    GateState,
    StageName,
    StageStatus,
)


def _request(
    policy_dir: Path,
    resolved: ResolvedCommitPair,
) -> ReviewRequest:
    review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    return ReviewRequest(
        resolved=resolved,
        review_policy=review_policy,
        review_policy_version=review_version,
        compute_policy=compute_policy,
        compute_policy_version=compute_version,
        surface="cli",
    )


@pytest.mark.asyncio
async def test_missing_objects_fail_at_construct_merge(
    git_repository: Path, policy_dir: Path
) -> None:
    report = await run_review_pipeline(
        _request(
            policy_dir,
            ResolvedCommitPair(
                source_repository=str(git_repository),
                target_ref="main",
                target_head_oid="a" * 40,
                proposed_ref="HEAD",
                proposed_head_oid="b" * 40,
            ),
        )
    )
    assert report.gate_state is GateState.ERROR
    assert report.merge_tree_oid is None
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert tuple(by_stage) == PIPELINE_STAGE_ORDER
    assert by_stage[StageName.DERIVE_IDENTITY].status is StageStatus.COMPLETED
    assert by_stage[StageName.CONSTRUCT_MERGE].status is StageStatus.FAILED
    assert by_stage[StageName.PREPARE_WORKSPACE].status is StageStatus.NOT_STARTED
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.NOT_STARTED
    assert by_stage[StageName.EVALUATE_GATE].status is StageStatus.COMPLETED
    assert by_stage[StageName.PUBLISH].status is StageStatus.COMPLETED


@pytest.mark.asyncio
async def test_clean_merge_prepares_workspace_then_stops_at_context(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    report = await run_review_pipeline(
        _request(
            policy_dir,
            ResolvedCommitPair(
                source_repository=str(git_repository),
                target_ref="main",
                target_head_oid=oid,
                proposed_ref="HEAD",
                proposed_head_oid=oid,
            ),
        )
    )
    assert report.gate_state is GateState.ERROR
    assert report.merge_tree_oid is not None
    assert len(report.merge_tree_oid) >= 40
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert tuple(by_stage) == PIPELINE_STAGE_ORDER
    assert by_stage[StageName.CONSTRUCT_MERGE].status is StageStatus.COMPLETED
    assert by_stage[StageName.PREPARE_WORKSPACE].status is StageStatus.COMPLETED
    assert by_stage[StageName.GATHER_CONTEXT].status is StageStatus.FAILED
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.NOT_STARTED
    assert "not implemented" in (by_stage[StageName.GATHER_CONTEXT].detail or "")


@pytest.mark.asyncio
async def test_conflict_does_not_prepare_workspace(git_repository: Path, policy_dir: Path) -> None:
    commit_files(git_repository, {"file.txt": "base\n"}, "base")
    checkout_new_branch(git_repository, "topic")
    proposed_oid = commit_files(git_repository, {"file.txt": "topic\n"}, "topic")
    git(git_repository, "checkout", "main")
    target_oid = commit_files(git_repository, {"file.txt": "main\n"}, "main")
    report = await run_review_pipeline(
        _request(
            policy_dir,
            ResolvedCommitPair(
                source_repository=str(git_repository),
                target_ref="main",
                target_head_oid=target_oid,
                proposed_ref="topic",
                proposed_head_oid=proposed_oid,
            ),
        )
    )
    assert report.gate_state is GateState.ERROR
    assert report.merge_tree_oid is None
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert by_stage[StageName.CONSTRUCT_MERGE].status is StageStatus.FAILED
    assert "conflict" in (by_stage[StageName.CONSTRUCT_MERGE].detail or "").lower()
    assert by_stage[StageName.PREPARE_WORKSPACE].status is StageStatus.NOT_STARTED
