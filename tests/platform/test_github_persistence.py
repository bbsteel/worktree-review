from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot, PublicationIntent
from worktree_review.server.state import GitHubChangeRequestLocator, StateConflictError


def _snapshot(attempt_id: str = "a1") -> AttemptExecutionSnapshot:
    return AttemptExecutionSnapshot(
        attempt_id=attempt_id,
        change_request=GitHubChangeRequestLocator(
            installation_id=7, repository="octo/example", pull_request_number=42
        ),
        request_key=ReviewRequestKey(
            source_repository="octo/example",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
        ),
        proposed_ref="feature",
        review_policy_semver="1.0.0",
        review_policy_sha256="d" * 64,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
        provider_profile_id="profile-1",
        delivery_id="delivery-1",
    )


def _event(attempt_id: str, sequence: int) -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=datetime.now(UTC),
        attempt_id=attempt_id,
        surface="github",
        event_type="attempt.created",
        payload={"source": "github-pull-request"},
    )


@pytest.mark.asyncio
async def test_snapshot_and_queued_check_are_recoverable_before_result() -> None:
    store = InMemoryGitHubReviewStore()
    snapshot = _snapshot()
    await store.save_execution_snapshot(snapshot)
    await store.set_check_run_id("a1", 99)
    recovered = await store.list_recoverable_queued()
    assert recovered == (snapshot,)
    assert await store.get_check_run_id("a1") == 99
    dumped = snapshot.as_public_dict()
    assert "token" not in dumped
    assert "credential" not in dumped


@pytest.mark.asyncio
async def test_publication_failure_can_retry_same_check_without_republishing() -> None:
    store = InMemoryGitHubReviewStore()
    await store.save_execution_snapshot(_snapshot())
    await store.set_check_run_id("a1", 99)
    intent = PublicationIntent(
        attempt_id="a1",
        check_run_id=99,
        intent="terminal-check",
        payload={"check_run_id": 99},
    )
    await store.enqueue_publication(intent)
    claimed = await store.claim_publication("a1")
    assert claimed is not None
    await store.mark_publication("a1", status=PublicationStatus.FAILED, error="GitHub 502")
    retry = await store.claim_publication("a1")
    assert retry is not None
    assert retry.check_run_id == 99
    await store.mark_publication("a1", status=PublicationStatus.PUBLISHED)
    with pytest.raises(StateConflictError, match="already completed"):
        await store.enqueue_publication(intent)


@pytest.mark.asyncio
async def test_events_and_results_are_durable_and_results_immutable() -> None:
    store = InMemoryGitHubReviewStore()
    await store.append_review_event(_event("a1", 1))
    await store.append_review_event(_event("a1", 2))
    assert len(await store.list_review_events("a1")) == 2
    await store.save_review_result("a1", '{"gate_state":"Passed"}')
    with pytest.raises(StateConflictError, match="immutable"):
        await store.save_review_result("a1", '{"gate_state":"Blocked"}')
    assert await store.list_recoverable_queued() == ()
    same = await store.record_webhook_idempotency(
        installation_id=7, delivery_id="d1", attempt_id="a1", request_digest="abc"
    )
    again = await store.record_webhook_idempotency(
        installation_id=7, delivery_id="d1", attempt_id="ignored", request_digest="abc"
    )
    assert same == again == "a1"
    with pytest.raises(StateConflictError, match="different request"):
        await store.record_webhook_idempotency(
            installation_id=7, delivery_id="d1", attempt_id="a2", request_digest="other"
        )
