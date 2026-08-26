"""Surface-neutral review result (PRD §19). Adapters map this; they do not redefine it."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from mergegate.core.findings import Finding
from mergegate.core.identity import PolicyVersionIdentity, ResolvedCommitPair


class GateState(StrEnum):
    """PRD §14. The evaluator returns only the four terminal states."""

    AWAITING_REVIEW = "Awaiting review"
    IN_PROGRESS = "In progress"
    PASSED = "Passed"
    PASSED_WITH_BYPASS = "Passed with bypass"
    BLOCKED = "Blocked"
    ERROR = "Error"


TERMINAL_GATE_STATES: frozenset[GateState] = frozenset(
    {
        GateState.PASSED,
        GateState.PASSED_WITH_BYPASS,
        GateState.BLOCKED,
        GateState.ERROR,
    }
)


class StageName(StrEnum):
    """The nine shared pipeline stages (PRD §21.1; TECH-DESIGN D3)."""

    DERIVE_IDENTITY = "derive-identity"
    CONSTRUCT_MERGE = "construct-merge"
    PREPARE_WORKSPACE = "prepare-workspace"
    GATHER_CONTEXT = "gather-context"
    RUN_DIMENSIONS = "run-dimensions"
    VERIFY_DEDUP = "verify-dedup"
    CHECK_COMPLETENESS = "check-completeness"
    EVALUATE_GATE = "evaluate-gate"
    PUBLISH = "publish"


PIPELINE_STAGE_ORDER: tuple[StageName, ...] = tuple(StageName)


class StageStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_STARTED = "not-started"


class StageOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: StageName
    status: StageStatus
    detail: str | None = None


class ExecutionRecord(BaseModel):
    """Append-only stage outcomes for one review attempt."""

    model_config = ConfigDict(frozen=True)

    outcomes: tuple[StageOutcome, ...] = ()

    def with_outcome(self, outcome: StageOutcome) -> ExecutionRecord:
        return ExecutionRecord(outcomes=(*self.outcomes, outcome))


class DimensionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension_id: str
    status: StageStatus
    detail: str | None = None


class CoverageRecord(BaseModel):
    """Disclosed coverage. Missing mandatory context makes required coverage incomplete."""

    model_config = ConfigDict(frozen=True)

    required_coverage_complete: bool
    optional_missing: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    unreviewable: tuple[str, ...] = ()
    reviewed: tuple[str, ...] = ()


class ReviewReport(BaseModel):
    """Platform-independent result. Both CLI and GitHub adapters render this model."""

    model_config = ConfigDict(frozen=True)

    gate_state: GateState
    resolved: ResolvedCommitPair
    merge_tree_oid: str | None
    review_policy_version: PolicyVersionIdentity
    compute_policy_version: PolicyVersionIdentity
    execution: ExecutionRecord
    findings: tuple[Finding, ...] = ()
    coverage: CoverageRecord | None = None
    dimension_outcomes: tuple[DimensionOutcome, ...] = ()
    summary: str
    error_detail: str | None = None
