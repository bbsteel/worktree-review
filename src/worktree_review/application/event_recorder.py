"""Per-Attempt sequenced recorder: persist, then broadcast."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from worktree_review.application.review_events import (
    ReviewEvent,
    ReviewEventSink,
    ReviewEventStore,
    SurfaceName,
    redact_payload,
    utc_now,
)
from worktree_review.core.report import ReviewProgressEvent

logger = logging.getLogger(__name__)


class MemoryReviewEventStore:
    def __init__(self) -> None:
        self._events: dict[str, list[ReviewEvent]] = {}

    async def append(self, event: ReviewEvent) -> None:
        self._events.setdefault(event.attempt_id, []).append(event)

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        return tuple(self._events.get(attempt_id, ()))


class ReviewEventRecorder:
    def __init__(
        self,
        store: ReviewEventStore,
        sinks: Sequence[ReviewEventSink] = (),
    ) -> None:
        self._store = store
        self._sinks = tuple(sinks)
        self._sequences: dict[str, int] = {}

    def next_sequence(self, attempt_id: str) -> int:
        current = self._sequences.get(attempt_id, 0) + 1
        self._sequences[attempt_id] = current
        return current

    async def record(
        self,
        *,
        attempt_id: str,
        surface: SurfaceName,
        event_type: str,
        payload: dict[str, Any],
        reconstructed: bool = False,
    ) -> ReviewEvent:
        event = ReviewEvent(
            sequence=self.next_sequence(attempt_id),
            occurred_at=utc_now(),
            attempt_id=attempt_id,
            surface=surface,
            event_type=event_type,
            payload=redact_payload(payload),
            reconstructed=reconstructed,
        )
        await self._store.append(event)
        for sink in self._sinks:
            try:
                await sink.publish(event)
            except Exception:
                logger.warning(
                    "review event sink failed after persist",
                    extra={"attempt_id": attempt_id, "sequence": event.sequence},
                    exc_info=True,
                )
        return event

    def map_progress(
        self,
        progress: ReviewProgressEvent,
        *,
        attempt_id: str,
        surface: SurfaceName,
    ) -> tuple[str, dict[str, Any]]:
        if progress.phase == "stage":
            event_type = f"stage.{progress.status}"
            payload: dict[str, Any] = {
                "stage": progress.name,
                "elapsed_seconds": progress.elapsed_seconds,
            }
        else:
            event_type = f"dimension.{progress.status}"
            payload = {
                "dimension_id": progress.name,
                "elapsed_seconds": progress.elapsed_seconds,
            }
        return event_type, payload
