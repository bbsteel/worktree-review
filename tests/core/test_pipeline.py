from __future__ import annotations

from pathlib import Path

import pytest

from mergegate.core.identity import ResolvedCommitPair
from mergegate.core.pipeline import ReviewRequest, run_review_pipeline
from mergegate.core.policy import load_compute_policy, load_review_policy
from mergegate.core.report import (
    PIPELINE_STAGE_ORDER,
    GateState,
    StageName,
    StageStatus,
)


@pytest.mark.asyncio
async def test_skeleton_pipeline_is_fail_closed(policy_dir: Path) -> None:
    review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    report = await run_review_pipeline(
        ReviewRequest(
            resolved=ResolvedCommitPair(
                source_repository="/tmp/example",
                target_ref="main",
                target_head_oid="a" * 40,
                proposed_ref="HEAD",
                proposed_head_oid="b" * 40,
            ),
            review_policy=review_policy,
            review_policy_version=review_version,
            compute_policy=compute_policy,
            compute_policy_version=compute_version,
            surface="cli",
        )
    )

    assert report.gate_state is GateState.ERROR
    assert report.merge_tree_oid is None
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert tuple(by_stage) == PIPELINE_STAGE_ORDER
    assert by_stage[StageName.DERIVE_IDENTITY].status is StageStatus.COMPLETED
    assert by_stage[StageName.CONSTRUCT_MERGE].status is StageStatus.FAILED
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.NOT_STARTED
    assert by_stage[StageName.EVALUATE_GATE].status is StageStatus.COMPLETED
    assert by_stage[StageName.PUBLISH].status is StageStatus.COMPLETED
