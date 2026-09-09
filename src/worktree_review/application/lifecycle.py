"""Run, gate, authority, publication, and bypass axes for Surface views."""

from enum import StrEnum

from worktree_review.core.report import GateState


class RunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ViewGateState(StrEnum):
    AWAITING_REVIEW = "awaiting_review"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    PASSED_WITH_BYPASS = "passed_with_bypass"
    BLOCKED = "blocked"
    ERROR = "error"


class Authority(StrEnum):
    LOCAL_NON_AUTHORITATIVE = "local_non_authoritative"
    AUTHORITATIVE = "authoritative"
    SUPERSEDED = "superseded"
    AUDIT_ONLY = "audit_only"


class PublicationStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    FAILED = "failed"


class BypassState(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    INVALIDATED = "invalidated"


CORE_GATE_TO_VIEW: dict[GateState, ViewGateState] = {
    GateState.AWAITING_REVIEW: ViewGateState.AWAITING_REVIEW,
    GateState.IN_PROGRESS: ViewGateState.IN_PROGRESS,
    GateState.PASSED: ViewGateState.PASSED,
    GateState.PASSED_WITH_BYPASS: ViewGateState.PASSED_WITH_BYPASS,
    GateState.BLOCKED: ViewGateState.BLOCKED,
    GateState.ERROR: ViewGateState.ERROR,
}


def project_gate_state(core: GateState) -> ViewGateState:
    return CORE_GATE_TO_VIEW[core]
