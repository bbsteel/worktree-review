"""Deterministic, pure gate evaluator (PRD §9.5, §14; TECH-DESIGN D4).

No model call participates. Model output may only influence which findings
exist; this function maps completion, coverage, findings, and bypass flags
onto a gate state.
"""

from pydantic import BaseModel, ConfigDict

from mergegate.core.findings import EVIDENCE_BAND_RANK, EvidenceBand, Finding
from mergegate.core.policy import ReviewPolicy
from mergegate.core.report import (
    CoverageRecord,
    DimensionOutcome,
    GateState,
    StageStatus,
)


class GateEvaluationInput(BaseModel):
    """Inputs to the pure evaluator. Callers resolve bypass applicability first."""

    model_config = ConfigDict(frozen=True)

    dimension_outcomes: tuple[DimensionOutcome, ...]
    coverage: CoverageRecord
    findings: tuple[Finding, ...]
    review_policy: ReviewPolicy


def finding_blocks_under_policy(finding: Finding, review_policy: ReviewPolicy) -> bool:
    """PRD §13: insufficient evidence never blocks, even if policy is misconfigured."""

    if finding.evidence_band is EvidenceBand.INSUFFICIENT:
        return False
    if finding.severity not in review_policy.blocking_severities:
        return False
    return (
        EVIDENCE_BAND_RANK[finding.evidence_band]
        >= EVIDENCE_BAND_RANK[review_policy.minimum_blocking_evidence_band]
    )


def evaluate_gate(evaluation_input: GateEvaluationInput) -> GateState:
    """Table-driven mapping to a terminal gate state.

    Properties:
    - any incomplete required dimension ⇒ ``Error``
    - required coverage incomplete ⇒ ``Error``
    - no unresolved blocking finding ⇒ not ``Blocked``
    """

    required = frozenset(evaluation_input.review_policy.required_dimensions)
    if not required:
        return GateState.ERROR

    outcomes_by_dimension: dict[str, list[DimensionOutcome]] = {}
    for outcome in evaluation_input.dimension_outcomes:
        outcomes_by_dimension.setdefault(outcome.dimension_id, []).append(outcome)
    if any(len(recorded) != 1 for recorded in outcomes_by_dimension.values()):
        return GateState.ERROR
    for dimension_id in required:
        recorded = outcomes_by_dimension.get(dimension_id)
        if recorded is None or recorded[0].status is not StageStatus.COMPLETED:
            return GateState.ERROR
    if not evaluation_input.coverage.required_coverage_complete:
        return GateState.ERROR

    blocking = [
        finding
        for finding in evaluation_input.findings
        if finding_blocks_under_policy(finding, evaluation_input.review_policy)
    ]
    unresolved = [finding for finding in blocking if not finding.bypass_applied]
    if unresolved:
        return GateState.BLOCKED
    if blocking:
        return GateState.PASSED_WITH_BYPASS
    return GateState.PASSED
