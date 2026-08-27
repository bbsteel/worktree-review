from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import checkout_new_branch, commit_files, git, head_oid

from worktree_review.core.identity import ResolvedCommitPair
from worktree_review.core.pipeline import ReviewRequest, run_review_pipeline
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.provider import ScriptedProvider
from worktree_review.core.report import (
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
    assert report.attempt_id
    assert report.request_key.proposed_head_oid == "b" * 40
    assert report.review_identity is None
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert tuple(by_stage) == PIPELINE_STAGE_ORDER
    assert by_stage[StageName.DERIVE_IDENTITY].status is StageStatus.COMPLETED
    assert by_stage[StageName.CONSTRUCT_MERGE].status is StageStatus.FAILED
    assert by_stage[StageName.PREPARE_WORKSPACE].status is StageStatus.NOT_STARTED
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.NOT_STARTED
    assert by_stage[StageName.EVALUATE_GATE].status is StageStatus.COMPLETED
    assert by_stage[StageName.PUBLISH].status is StageStatus.COMPLETED


@pytest.mark.asyncio
async def test_clean_merge_runs_dimensions_then_stops_at_verify(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    provider = ScriptedProvider(payloads={"correctness": {"findings": []}})
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
        ),
        provider=provider,
    )
    assert report.gate_state is GateState.ERROR
    assert report.merge_tree_oid is not None
    assert report.review_identity is not None
    assert report.review_identity.candidate.merge_tree_oid == report.merge_tree_oid
    assert len(report.merge_tree_oid) >= 40
    assert report.coverage is not None
    assert report.coverage.required_coverage_complete is True
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert tuple(by_stage) == PIPELINE_STAGE_ORDER
    assert by_stage[StageName.CONSTRUCT_MERGE].status is StageStatus.COMPLETED
    assert by_stage[StageName.PREPARE_WORKSPACE].status is StageStatus.COMPLETED
    assert by_stage[StageName.GATHER_CONTEXT].status is StageStatus.COMPLETED
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.COMPLETED
    assert by_stage[StageName.VERIFY_DEDUP].status is StageStatus.FAILED
    assert "not implemented" in (by_stage[StageName.VERIFY_DEDUP].detail or "")
    assert provider.dimension_ids_called == ["correctness"]


@pytest.mark.asyncio
async def test_scripted_findings_are_visible_but_cannot_pass(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    provider = ScriptedProvider(
        payloads={
            "correctness": {
                "findings": [
                    {
                        "path": "README",
                        "start_line": 1,
                        "end_line": 1,
                        "quoted_text": "hello",
                        "severity": "major",
                        "evidence_band": "supported",
                        "problem_statement": "placeholder",
                        "expected_impact": "none",
                        "repair_guidance": None,
                    }
                ]
            }
        }
    )
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
        ),
        provider=provider,
    )
    assert report.gate_state is GateState.ERROR
    assert report.findings == ()
    assert len(report.draft_findings) == 1
    assert report.draft_findings[0].problem_statement == "placeholder"
    assert report.usage


@pytest.mark.asyncio
async def test_budget_preflight_refuses_to_start_dimensions(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    provider = ScriptedProvider(
        payloads={"correctness": {"findings": []}},
        estimated_input_tokens=10_000_000,
    )
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
        ),
        provider=provider,
    )
    assert report.gate_state is GateState.ERROR
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.FAILED
    assert "exceeds" in (report.error_detail or "")
    assert provider.dimension_ids_called == []


@pytest.mark.asyncio
async def test_in_flight_budget_stops_further_dimensions(
    git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    two_dimensions = review_policy.model_copy(
        update={"required_dimensions": ("correctness", "security")}
    )
    provider = ScriptedProvider(
        payloads={
            "correctness": {"findings": []},
            "security": {"findings": []},
        },
        estimated_input_tokens=10,
        measured_input_tokens=1_000_000,
    )
    report = await run_review_pipeline(
        ReviewRequest(
            resolved=ResolvedCommitPair(
                source_repository=str(git_repository),
                target_ref="main",
                target_head_oid=oid,
                proposed_ref="HEAD",
                proposed_head_oid=oid,
            ),
            review_policy=two_dimensions,
            review_policy_version=review_version,
            compute_policy=compute_policy,
            compute_policy_version=compute_version,
            surface="cli",
        ),
        provider=provider,
    )
    by_id = {outcome.dimension_id: outcome for outcome in report.dimension_outcomes}
    assert by_id["correctness"].status is StageStatus.COMPLETED
    assert by_id["security"].status is StageStatus.NOT_STARTED
    assert provider.dimension_ids_called == ["correctness"]
    assert any(record.kind.value == "measured" for record in report.usage)


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


@pytest.mark.asyncio
async def test_unreviewable_change_skips_dimensions(git_repository: Path, policy_dir: Path) -> None:
    target_oid = head_oid(git_repository)
    checkout_new_branch(git_repository, "topic")
    blob = git_repository / "data.bin"
    blob.write_bytes(b"hello\x00world")
    git(git_repository, "add", "data.bin")
    git(git_repository, "commit", "-m", "add binary")
    proposed_oid = head_oid(git_repository)
    git(git_repository, "checkout", "main")
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
    assert report.coverage is not None
    assert report.coverage.required_coverage_complete is False
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    assert by_stage[StageName.GATHER_CONTEXT].status is StageStatus.COMPLETED
    assert by_stage[StageName.RUN_DIMENSIONS].status is StageStatus.NOT_STARTED
    assert "unreviewable" in (report.error_detail or "")
