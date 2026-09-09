from __future__ import annotations

import pytest

from worktree_review.application.event_recorder import MemoryReviewEventStore, ReviewEventRecorder
from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.report import ReviewProgressEvent, StageName


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[ReviewEvent] = []
        self.fail = False

    async def publish(self, event: ReviewEvent) -> None:
        if self.fail:
            raise RuntimeError("sink unavailable")
        self.events.append(event)


class FailingStore:
    async def append(self, event: ReviewEvent) -> None:
        raise RuntimeError("authoritative store failed")

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        return ()


@pytest.mark.asyncio
async def test_sequence_increments_and_redacts_secrets() -> None:
    store = MemoryReviewEventStore()
    recorder = ReviewEventRecorder(store)
    first = await recorder.record(
        attempt_id="a1",
        surface="web",
        event_type="attempt.created",
        payload={"source": "local-worktree"},
    )
    second = await recorder.record(
        attempt_id="a1",
        surface="web",
        event_type="inputs.resolved",
        payload={"api_key": "sk-secret", "target": "main"},
    )
    assert first.sequence == 1
    assert second.sequence == 2
    assert second.payload["api_key"] == "[redacted]"
    assert second.payload["target"] == "main"
    assert (await store.list_events("a1")) == (first, second)


@pytest.mark.asyncio
async def test_store_failure_prevents_broadcast() -> None:
    sink = RecordingSink()
    recorder = ReviewEventRecorder(FailingStore(), sinks=(sink,))
    with pytest.raises(RuntimeError, match="authoritative store failed"):
        await recorder.record(
            attempt_id="a1",
            surface="cli",
            event_type="attempt.created",
            payload={},
        )
    assert sink.events == []


@pytest.mark.asyncio
async def test_sink_failure_does_not_roll_back_store() -> None:
    store = MemoryReviewEventStore()
    sink = RecordingSink()
    sink.fail = True
    recorder = ReviewEventRecorder(store, sinks=(sink,))
    event = await recorder.record(
        attempt_id="a1",
        surface="cli",
        event_type="attempt.created",
        payload={},
    )
    assert (await store.list_events("a1")) == (event,)


def test_progress_mapping_does_not_invent_provider_calls() -> None:
    recorder = ReviewEventRecorder(MemoryReviewEventStore())
    event_type, payload = recorder.map_progress(
        ReviewProgressEvent(
            phase="stage",
            name=StageName.CONSTRUCT_MERGE.value,
            status="started",
            elapsed_seconds=0,
        ),
        attempt_id="a1",
        surface="web",
    )
    assert event_type == "stage.started"
    assert payload["stage"] == StageName.CONSTRUCT_MERGE.value
    assert "provider_call" not in event_type
