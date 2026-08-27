from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from worktree_review.core.findings import EvidenceBand, Finding, Severity
from worktree_review.core.gate import GateEvaluationInput, evaluate_gate
from worktree_review.core.policy import ReviewPolicy
from worktree_review.core.report import (
    CoverageRecord,
    DimensionOutcome,
    GateState,
    StageStatus,
)

POLICY = ReviewPolicy.model_validate(
    {
        "schema": "worktree-review.review-policy/v1",
        "version": "1.0.0",
        "required_dimensions": ["correctness", "security"],
        "blocking_severities": ["critical", "major"],
        "minimum_blocking_evidence_band": "supported",
    }
)


def _finding(
    *,
    severity: Severity = Severity.MAJOR,
    evidence_band: EvidenceBand = EvidenceBand.SUPPORTED,
    bypass_applied: bool = False,
) -> Finding:
    return Finding(
        fingerprint="abc",
        severity=severity,
        evidence_band=evidence_band,
        problem_statement="broken contract",
        expected_impact="user-visible failure",
        bypass_applied=bypass_applied,
    )


def _input(
    *,
    dimension_status: StageStatus = StageStatus.COMPLETED,
    coverage_complete: bool = True,
    findings: tuple[Finding, ...] = (),
) -> GateEvaluationInput:
    return GateEvaluationInput(
        dimension_outcomes=(
            DimensionOutcome(dimension_id="correctness", status=dimension_status),
            DimensionOutcome(dimension_id="security", status=StageStatus.COMPLETED),
        ),
        coverage=CoverageRecord(required_coverage_complete=coverage_complete),
        findings=findings,
        review_policy=POLICY,
    )


def test_complete_review_with_no_findings_passes() -> None:
    assert evaluate_gate(_input()) is GateState.PASSED


def test_unresolved_blocking_finding_blocks() -> None:
    assert evaluate_gate(_input(findings=(_finding(),))) is GateState.BLOCKED


def test_bypassed_blocking_findings_pass_with_bypass() -> None:
    assert (
        evaluate_gate(_input(findings=(_finding(bypass_applied=True),)))
        is GateState.PASSED_WITH_BYPASS
    )


def test_incomplete_dimension_is_error_even_with_no_findings() -> None:
    assert evaluate_gate(_input(dimension_status=StageStatus.FAILED)) is GateState.ERROR


def test_duplicate_dimension_outcomes_fail_closed() -> None:
    mixed = GateEvaluationInput(
        dimension_outcomes=(
            DimensionOutcome(dimension_id="correctness", status=StageStatus.COMPLETED),
            DimensionOutcome(dimension_id="correctness", status=StageStatus.FAILED),
            DimensionOutcome(dimension_id="security", status=StageStatus.COMPLETED),
        ),
        coverage=CoverageRecord(required_coverage_complete=True),
        findings=(),
        review_policy=POLICY,
    )
    assert evaluate_gate(mixed) is GateState.ERROR
    duplicated_completed = GateEvaluationInput(
        dimension_outcomes=(
            DimensionOutcome(dimension_id="correctness", status=StageStatus.COMPLETED),
            DimensionOutcome(dimension_id="correctness", status=StageStatus.COMPLETED),
            DimensionOutcome(dimension_id="security", status=StageStatus.COMPLETED),
        ),
        coverage=CoverageRecord(required_coverage_complete=True),
        findings=(),
        review_policy=POLICY,
    )
    assert evaluate_gate(duplicated_completed) is GateState.ERROR


def test_incomplete_coverage_is_error() -> None:
    assert evaluate_gate(_input(coverage_complete=False)) is GateState.ERROR


def test_insufficient_evidence_never_blocks() -> None:
    finding = _finding(severity=Severity.CRITICAL, evidence_band=EvidenceBand.INSUFFICIENT)
    assert evaluate_gate(_input(findings=(finding,))) is GateState.PASSED


def test_minor_findings_do_not_block_under_default_policy() -> None:
    finding = _finding(severity=Severity.MINOR)
    assert evaluate_gate(_input(findings=(finding,))) is GateState.PASSED


@given(status=st.sampled_from([StageStatus.FAILED, StageStatus.NOT_STARTED]))
def test_any_incomplete_required_dimension_is_error(status: StageStatus) -> None:
    result = evaluate_gate(_input(dimension_status=status, findings=(_finding(),)))
    assert result is GateState.ERROR


@given(bypass_applied=st.booleans())
def test_no_unresolved_blocking_finding_is_not_blocked(bypass_applied: bool) -> None:
    finding = _finding(bypass_applied=bypass_applied)
    if bypass_applied:
        assert evaluate_gate(_input(findings=(finding,))) is not GateState.BLOCKED
    else:
        assert evaluate_gate(_input(findings=(finding,))) is GateState.BLOCKED
