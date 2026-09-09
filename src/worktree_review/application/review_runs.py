"""ReviewRunStore protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.report import ReviewReport


class ReviewRunRecord:
    def __init__(
        self,
        *,
        attempt_id: str,
        run_status: RunStatus,
        created_at: datetime,
        result_json: str | None = None,
        cost_usd: str | None = None,
        cost_unknown: bool = False,
        interrupted: bool = False,
        request_json: str | None = None,
        gate_state: str | None = None,
    ) -> None:
        self.attempt_id = attempt_id
        self.run_status = run_status
        self.created_at = created_at
        self.result_json = result_json
        self.cost_usd = cost_usd
        self.cost_unknown = cost_unknown
        self.interrupted = interrupted
        self.request_json = request_json
        self.gate_state = gate_state


class OverviewAggregate:
    def __init__(
        self,
        *,
        attempt_count: int,
        passed_count: int,
        blocked_count: int,
        error_count: int,
        known_cost_usd: str,
        unknown_cost_record_count: int,
    ) -> None:
        self.attempt_count = attempt_count
        self.passed_count = passed_count
        self.blocked_count = blocked_count
        self.error_count = error_count
        self.known_cost_usd = known_cost_usd
        self.unknown_cost_record_count = unknown_cost_record_count


class ReviewRunStore(Protocol):
    async def create_attempt_with_initial_event_and_idempotency(
        self,
        *,
        attempt_id: str,
        idempotency_key: str,
        request_digest: str,
        initial_event: ReviewEvent,
        run_status: RunStatus = RunStatus.QUEUED,
    ) -> str: ...

    async def append_event(self, event: ReviewEvent) -> None: ...

    async def update_run_status(self, attempt_id: str, run_status: RunStatus) -> None: ...

    async def save_result(
        self, report: ReviewReport, *, cost_usd: str | None, cost_unknown: bool
    ) -> None: ...

    async def get_run(self, attempt_id: str) -> ReviewRunRecord | None: ...

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]: ...

    async def mark_interrupted(self, attempt_id: str) -> None: ...

    async def overview_aggregate(self) -> OverviewAggregate: ...
