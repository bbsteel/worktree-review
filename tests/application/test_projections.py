from __future__ import annotations

from decimal import Decimal

from worktree_review.application.projections import (
    NOT_REPORTED_REASON,
    project_coverage_files,
    project_usage_calls,
)
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
    ExecutionRecord,
    GateState,
    ReviewReport,
)

_POLICY = PolicyVersionIdentity(semver="0.1.0", sha256="a" * 64)


def _report(usage: tuple[UsageRecord, ...] = ()) -> ReviewReport:
    return ReviewReport(
        gate_state=GateState.PASSED,
        attempt_id="a1",
        request_key=ReviewRequestKey(
            source_repository="demo/local",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            review_policy_version=_POLICY,
        ),
        resolved=ResolvedCommitPair(
            source_repository="demo/local",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_ref="HEAD",
            proposed_head_oid="b" * 40,
            proposed_source=ProposedSource.COMMITTED_REF,
        ),
        merge_tree_oid="c" * 40,
        review_identity=None,
        review_policy_version=_POLICY,
        compute_policy_version=_POLICY,
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="claude",
            data_destination="https://api.anthropic.com",
            known_retention="none",
        ),
        execution=ExecutionRecord(),
        coverage=None,
        usage=usage,
        summary="ok",
        error_detail=None,
    )


def test_coverage_does_not_guess_reason_from_path_or_position() -> None:
    coverage = CoverageRecord(
        required_coverage_complete=False,
        reviewed=("src/ok.py",),
        mandatory_missing=("src/secret.py", "README.md"),
        optional_missing=("AGENTS.md",),
        excluded=("vendor/lib.py",),
        unreviewable=("bin/app",),
    )
    files = project_coverage_files(coverage)
    missing = [row for row in files if row["category"] == "mandatory-missing"]
    assert [row["path"] for row in missing] == ["src/secret.py", "README.md"]
    assert all(row["reason"] == NOT_REPORTED_REASON for row in missing)
    assert missing[0]["reason"] == missing[1]["reason"]
    secret = next(row for row in files if row["path"] == "src/secret.py")
    readme = next(row for row in files if row["path"] == "README.md")
    assert secret["rule"] == readme["rule"] == "mandatory-glob"
    reviewed = next(row for row in files if row["path"] == "src/ok.py")
    assert reviewed["reason"] is None
    assert reviewed["rule"] is None


def test_usage_does_not_invent_dimension_or_elapsed_from_tuple_order() -> None:
    report = _report(
        usage=(
            UsageRecord(
                kind=UsageKind.MEASURED,
                input_tokens=10,
                output_tokens=4,
                cost_usd=Decimal("0.02"),
                provider="anthropic",
                model="claude",
            ),
            UsageRecord(
                kind=UsageKind.MEASURED,
                input_tokens=8,
                output_tokens=2,
                cost_usd=None,
                provider="anthropic",
                model="claude",
            ),
        )
    )
    calls = project_usage_calls(report)
    assert [call["ordinal"] for call in calls] == [1, 2]
    assert all(call["dimension_id"] is None for call in calls)
    assert all(call["elapsed_ms"] is None for call in calls)
    assert all(call["dimension_id_status"] == "not-reported" for call in calls)
    assert all(call["elapsed_status"] == "not-reported" for call in calls)
    assert calls[0]["cost_unknown"] is False
    assert calls[1]["cost_unknown"] is True
