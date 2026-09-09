"""Surface-neutral review result (PRD §19). Adapters map this; they do not redefine it."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.findings import Finding
from worktree_review.core.identity import (
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.provider import UsageRecord


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
    PREPARE_REVIEW_WORKTREE = "prepare-review-worktree"  # Pre-Alpha in-place; was prepare-workspace
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


class ReviewProgressEvent(BaseModel):
    """Non-authoritative progress signal for interactive invoking surfaces."""

    model_config = ConfigDict(frozen=True)

    phase: Literal["stage", "dimension"]
    name: str
    status: Literal["started", "completed", "failed", "not-started"]
    elapsed_seconds: float = Field(ge=0)


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
    """Disclosed coverage. Missing mandatory or unreviewable-in-scope content is incomplete."""

    model_config = ConfigDict(frozen=True)

    required_coverage_complete: bool
    mandatory_missing: tuple[str, ...] = ()
    optional_missing: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    unreviewable: tuple[str, ...] = ()
    reviewed: tuple[str, ...] = ()


class ComputePolicyDisclosure(BaseModel):
    """Provider transmission details that every surface must make visible."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    data_destination: str
    known_retention: str
    provider_configuration_fingerprint: str | None = None


class ReviewCallPlan(BaseModel):
    """The bounded provider work planned after context gathering and pre-flight."""

    model_config = ConfigDict(frozen=True)

    call_count: int = Field(ge=0)
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens_per_call: int = Field(ge=1)


class ReviewReport(BaseModel):
    """Platform-independent result. Both CLI and GitHub adapters render this model."""

    model_config = ConfigDict(frozen=True)

    gate_state: GateState
    attempt_id: str
    request_key: ReviewRequestKey
    resolved: ResolvedCommitPair
    merge_tree_oid: str | None
    review_identity: ReviewIdentity | None
    review_policy_version: PolicyVersionIdentity
    compute_policy_version: PolicyVersionIdentity
    compute_policy_disclosure: ComputePolicyDisclosure
    execution: ExecutionRecord
    findings: tuple[Finding, ...] = ()
    draft_findings: tuple[Finding, ...] = ()
    coverage: CoverageRecord | None = None
    dimension_outcomes: tuple[DimensionOutcome, ...] = ()
    usage: tuple[UsageRecord, ...] = ()
    call_plan: ReviewCallPlan | None = None
    summary: str
    error_detail: str | None = None
