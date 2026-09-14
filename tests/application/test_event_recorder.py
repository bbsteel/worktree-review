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


def test_scrub_secret_content_redacts_credentials() -> None:
    from worktree_review.application.review_events import scrub_secret_content

    assert "sk-live-secret-value" not in scrub_secret_content(
        "401 Unauthorized: key sk-live-secret-value was rejected"
    )
    assert "Bearer" not in scrub_secret_content("Bearer abcdef123456789")
    assert "supersecret" not in scrub_secret_content("api_key=supersecret123")
    monkeypatched = scrub_secret_content("plain error without secrets")
    assert monkeypatched == "plain error without secrets"


def test_redact_payload_scrubs_string_values() -> None:
    from worktree_review.application.review_events import redact_payload

    payload = redact_payload({"safe_detail": "HTTP 401 for sk-ant-secret12345678"})
    assert "sk-ant-secret12345678" not in str(payload)


def test_scrub_secret_content_covers_arbitrary_credential_env_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from worktree_review.application.review_events import scrub_secret_content

    monkeypatch.setenv("MY_VENDOR_PROVIDER_TOKEN", "vendor-token-value-123")
    assert "vendor-token-value-123" not in scrub_secret_content(
        "handshake failed with vendor-token-value-123"
    )
    # Short values (under the minimum length) are left alone.
    monkeypatch.setenv("MY_OTHER_KEY", "tiny")
    assert "tiny" in scrub_secret_content("value was tiny")


def test_redact_payload_recurses_into_lists() -> None:
    from worktree_review.application.review_events import redact_payload

    payload = redact_payload(
        {"safe_detail": "ok", "items": ["call failed for sk-nested-secret-999", {"token": "abc"}]}
    )
    rendered = str(payload)
    assert "sk-nested-secret-999" not in rendered
    assert "abc" not in rendered


def test_internal_errors_use_fixed_text_not_arbitrary_exception_messages() -> None:
    from worktree_review.application.review_events import SafeErrorCategory, safe_error_payload

    payload = safe_error_payload(RuntimeError("db password hunter2 leaked"))
    assert payload["category"] == SafeErrorCategory.INTERNAL.value
    assert "hunter2" not in payload["safe_detail"]

    from worktree_review.core.errors import ProviderError

    provider_payload = safe_error_payload(ProviderError("HTTP 401 from provider"))
    assert provider_payload["category"] == SafeErrorCategory.PROVIDER.value
    assert "401" in provider_payload["safe_detail"]
