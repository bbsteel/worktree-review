from __future__ import annotations

from worktree_review.core.findings import EvidenceBand, EvidenceSource, EvidenceSpan, Finding
from worktree_review.core.identity import (
    PolicyVersionIdentity,
    ProposedSource,
    ResolvedCommitPair,
    ReviewRequestKey,
)
from worktree_review.core.provider import UsageKind, UsageRecord
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    CoverageRecord,
    DimensionOutcome,
    ExecutionRecord,
    GateState,
    ReviewCallPlan,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from worktree_review.platform.cli.terminal import render_call_plan, render_text_report


def _policy_version(sha256: str) -> PolicyVersionIdentity:
    return PolicyVersionIdentity(semver="0.1.0", sha256=sha256 * 64)


def _report(
    *,
    findings: tuple[Finding, ...],
    draft_findings: tuple[Finding, ...],
    usage: tuple[UsageRecord, ...] = (),
) -> ReviewReport:
    review_policy_version = _policy_version("a")
    compute_policy_version = _policy_version("b")
    resolved = ResolvedCommitPair(
        source_repository="/repo",
        target_ref="HEAD",
        target_head_oid="1" * 40,
        proposed_ref="WORKTREE",
        proposed_head_oid="2" * 40,
        proposed_source=ProposedSource.CURRENT_WORKTREE_SNAPSHOT,
    )
    return ReviewReport(
        gate_state=GateState.BLOCKED,
        attempt_id="attempt-1",
        request_key=ReviewRequestKey(
            source_repository=resolved.source_repository,
            target_ref=resolved.target_ref,
            target_head_oid=resolved.target_head_oid,
            proposed_head_oid=resolved.proposed_head_oid,
            review_policy_version=review_policy_version,
        ),
        resolved=resolved,
        merge_tree_oid="3" * 40,
        review_identity=None,
        review_policy_version=review_policy_version,
        compute_policy_version=compute_policy_version,
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="scripted",
            data_destination="https://api.anthropic.com",
            known_retention="test retention",
        ),
        execution=ExecutionRecord(
            outcomes=(StageOutcome(stage=StageName.PUBLISH, status=StageStatus.COMPLETED),)
        ),
        findings=findings,
        draft_findings=draft_findings,
        coverage=CoverageRecord(required_coverage_complete=True),
        dimension_outcomes=(
            DimensionOutcome(
                dimension_id="correctness",
                status=StageStatus.COMPLETED,
            ),
        ),
        usage=usage,
        summary="Review completed.",
    )


def test_terminal_call_plan_is_explicit_about_bounded_work() -> None:
    rendered = render_call_plan(
        ReviewCallPlan(
            call_count=2,
            estimated_input_tokens=38_000,
            max_output_tokens_per_call=4096,
        )
    )

    assert "Will make 2 model calls" in rendered
    assert "Estimated input: about 38,000 tokens" in rendered
    assert "Maximum output per call: 4,096 tokens" in rendered


def test_terminal_report_renders_measured_usage_and_unknown_provider_cost() -> None:
    report = _report(
        findings=(),
        draft_findings=(),
        usage=(
            UsageRecord(
                kind=UsageKind.ESTIMATED,
                input_tokens=38_000,
                output_tokens=8_192,
                provider="anthropic",
                model="scripted",
            ),
            UsageRecord(
                kind=UsageKind.MEASURED,
                input_tokens=42_318,
                output_tokens=2_104,
                provider="anthropic",
                model="scripted",
            ),
        ),
    )

    rendered = render_text_report(report)

    assert "Actual usage: 42,318 input / 2,104 output tokens" in rendered
    assert "Cost: Provider did not return; see account billing" in rendered


def _finding(*, problem_statement: str, evidence_band: EvidenceBand) -> Finding:
    return Finding(
        fingerprint="f" * 64,
        severity="major",
        evidence_band=evidence_band,
        problem_statement=problem_statement,
        expected_impact="request fails",
        evidence_spans=(
            EvidenceSpan(
                path="src/app.py",
                start_line=2,
                end_line=3,
                quoted_text="dangerous_call()\nnext_line()",
                source=EvidenceSource.REVIEW_WORKTREE,
                snapshot_identity="3" * 40,
            ),
        ),
        repair_guidance="validate the input",
        dimension_id="correctness",
    )


def test_terminal_report_renders_formal_and_draft_findings() -> None:
    report = _report(
        findings=(
            _finding(problem_statement="real problem", evidence_band=EvidenceBand.SUPPORTED),
        ),
        draft_findings=(
            _finding(
                problem_statement="unverified problem", evidence_band=EvidenceBand.INSUFFICIENT
            ),
        ),
    )

    rendered = render_text_report(report)

    assert "Findings: 1" in rendered
    assert "Finding 1: major / supported / correctness" in rendered
    assert "src/app.py:2-3 [review-worktree snapshot=" in rendered
    assert "quote: dangerous_call()" in rendered
    assert "problem: real problem" in rendered
    assert "impact: request fails" in rendered
    assert "repair: validate the input" in rendered
    assert "Dimensions:" in rendered
    assert "correctness: completed" in rendered
    assert "Provider/model: anthropic/scripted" in rendered
    assert "Data destination: https://api.anthropic.com" in rendered
    assert "Known retention: test retention" in rendered
    assert "Unverified draft findings: 1 (not evidence; verification did not complete)" in rendered
    assert "Draft finding 1: major / insufficient / correctness" in rendered
    assert "problem: unverified problem" in rendered


def test_terminal_report_escapes_terminal_control_sequences() -> None:
    report = _report(
        findings=(
            _finding(problem_statement="\x1b[31mred\x1b[0m", evidence_band=EvidenceBand.SUPPORTED),
        ),
        draft_findings=(),
    )

    rendered = render_text_report(report)

    assert "\x1b[31m" not in rendered
    assert r"\x1b[31mred\x1b[0m" in rendered
