"""PostgreSQL bypass persistence: CAS, replay, outbox, and concurrency (PRD §16, D9)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.platform.postgres_harness import database_url_for_name, open_postgres_url

from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.report import GateState
from worktree_review.server.state import (
    BypassStatus,
    CheckSyncStatus,
    GitHubChangeRequestLocator,
    PostgresAuthoritativeAttemptStore,
    StateConflictError,
)

pytest.importorskip("asyncpg")


@pytest.fixture(scope="session")
def postgres_base_url() -> Any:
    yield from open_postgres_url()


@pytest.fixture
async def store(postgres_base_url: str) -> Any:
    import asyncpg

    name = f"wr_bypass_{uuid.uuid4().hex[:12]}"
    connection = await asyncpg.connect(postgres_base_url)
    try:
        await connection.execute(f"CREATE DATABASE {name}")
    finally:
        await connection.close()
    pool = await asyncpg.create_pool(
        database_url_for_name(postgres_base_url, name),
        statement_cache_size=0,
    )
    try:
        attempt_store = PostgresAuthoritativeAttemptStore(pool)
        await attempt_store.initialise()
        # Migrations are additive and idempotent: a second pass must be a no-op.
        await attempt_store.initialise()
        yield attempt_store
    finally:
        await pool.close()
        # Let the loop finish closing connection transports before it is torn
        # down; otherwise GC collects half-closed sockets on a later test's
        # loop and trips PytestUnraisableExceptionWarning.
        await asyncio.sleep(0.05)


def _locator() -> GitHubChangeRequestLocator:
    return GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )


def _request_key(*, proposed_head_oid: str = "b" * 40) -> ReviewRequestKey:
    return ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid=proposed_head_oid,
        review_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="d" * 64),
    )


def _identity(request_key: ReviewRequestKey) -> ReviewIdentity:
    return ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_head_oid=request_key.proposed_head_oid,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=request_key.review_policy_version,
    )


_RISK_SNAPSHOT: dict[str, object] = {
    "severity": "major",
    "evidence_band": "supported",
    "problem_statement": "unsigned webhook fallback accepts requests",
    "expected_impact": "forged webhook calls merge",
    "evidence_spans": [
        {
            "path": "src/webhooks/verify.py",
            "start_line": 74,
            "end_line": 80,
            "source": "review-worktree",
            "snapshot_identity": "c" * 40,
            "change_kind": None,
        }
    ],
}
_RISK_DIGEST = "d" * 64
_POLICY_SHA = "d" * 64


async def _standing_blocked_attempt(
    store: PostgresAuthoritativeAttemptStore,
    locator: GitHubChangeRequestLocator,
    request_key: ReviewRequestKey,
) -> str:
    lease = await store.start_authoritative_attempt(
        change_request=locator,
        request_key=request_key,
    )
    await store.record_review_identity(
        attempt_id=lease.attempt_id,
        review_identity=_identity(request_key),
    )
    await store.claim_attempt_job(lease.attempt_id)
    await store.publish_if_authoritative(
        attempt_id=lease.attempt_id,
        request_key=request_key,
        review_identity=_identity(request_key),
        gate_state=GateState.BLOCKED,
    )
    return lease.attempt_id


def _bypass_kwargs(
    attempt_id: str, request_key: ReviewRequestKey, **overrides: Any
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "change_request": _locator(),
        "attempt_id": attempt_id,
        "finding_fingerprint": "fp-1",
        "actor_id": 123456,
        "actor_login": "maintainer",
        "reason": "accepted risk",
        "review_identity": _identity(request_key),
        "review_policy_sha256": _POLICY_SHA,
        "blocking_fingerprints": ("fp-1",),
        "risk_snapshot": _RISK_SNAPSHOT,
        "risk_digest": _RISK_DIGEST,
        "check_run_id": 98765,
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_postgres_bypass_cas_transition_replay_and_conflict(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)

    result = await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))
    assert result.gate_transitioned is True
    assert result.standing_gate_state is GateState.PASSED_WITH_BYPASS
    assert result.record.bypass_id >= 1
    current = await store.get_change_request_state(locator)
    assert current.standing_gate_state is GateState.PASSED_WITH_BYPASS
    assert current.standing_revision == result.standing_revision
    assert current.standing_revision >= 2  # publish + bypass

    replay = await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))
    assert replay.replayed is True
    assert replay.record.bypass_id == result.record.bypass_id
    assert len(await store.list_bypasses(attempt_id=attempt_id)) == 1

    with pytest.raises(StateConflictError, match="different bypass"):
        await store.apply_finding_bypass(
            **_bypass_kwargs(attempt_id, request_key, reason="different reason")
        )
    with pytest.raises(StateConflictError, match="different bypass"):
        await store.apply_finding_bypass(
            **_bypass_kwargs(attempt_id, request_key, actor_login="other-user", actor_id=999)
        )


@pytest.mark.asyncio
async def test_postgres_bypass_requires_standing_blocked_and_identity(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)

    wrong_identity = ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_head_oid=request_key.proposed_head_oid,
            merge_tree_oid="9" * 40,
        ),
        review_policy_version=request_key.review_policy_version,
    )
    with pytest.raises(StateConflictError, match="Review Identity changed"):
        await store.apply_finding_bypass(
            **_bypass_kwargs(attempt_id, request_key, review_identity=wrong_identity)
        )

    await store.start_authoritative_attempt(
        change_request=locator,
        request_key=request_key,
    )
    with pytest.raises(StateConflictError, match="standing authoritative"):
        await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))


@pytest.mark.asyncio
async def test_postgres_new_attempt_invalidates_bypasses_even_same_key(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)
    await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))

    # Same-identity retry: no carry-forward, the record expires (P3 §5.2).
    await store.start_authoritative_attempt(
        change_request=locator,
        request_key=request_key,
    )

    records = await store.list_bypasses(attempt_id=attempt_id)
    assert [record.status for record in records] == [BypassStatus.INVALIDATED]
    assert "superseded" in (records[0].invalidation_reason or "")
    assert records[0].invalidated_at is not None
    assert records[0].risk_snapshot["problem_statement"] == (
        "unsigned webhook fallback accepts requests"
    )
    # The pending sync intent went terminal-superseded with the standing loss.
    latest = await store.latest_standing_check_sync(attempt_id=attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_postgres_bypass_audit_and_intent_share_the_transaction(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)

    await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))

    events = await store.list_audit_events(repository=locator.repository)
    event_types = [event.event_type for event in events.events]
    assert "bypass_authorized" in event_types
    assert "gate_transition" in event_types
    assert "check_sync_queued" in event_types
    authorized = next(e for e in events.events if e.event_type == "bypass_authorized")
    assert authorized.actor_id == 123456
    assert authorized.actor_login == "maintainer"
    assert authorized.payload["risk_digest"] == _RISK_DIGEST

    intent = await store.latest_standing_check_sync(attempt_id=attempt_id)
    assert intent is not None
    assert intent.check_run_id == 98765
    assert intent.status is CheckSyncStatus.QUEUED


@pytest.mark.asyncio
async def test_postgres_unsafe_audit_payload_rolls_back_the_whole_bypass(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)

    # The reason reaches the audit payload; a recognized credential pattern
    # aborts the transaction — no partial bypass row may survive.
    with pytest.raises(ValueError, match="secret-shaped content"):
        await store.apply_finding_bypass(
            **_bypass_kwargs(
                attempt_id, request_key, reason="rolled back: ghp_abcdefghijklmnop0123"
            )
        )
    assert await store.list_bypasses(attempt_id=attempt_id) == ()
    current = await store.get_change_request_state(locator)
    assert current.standing_gate_state is GateState.BLOCKED


@pytest.mark.asyncio
async def test_postgres_standing_check_sync_claim_mark_and_recovery(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)
    await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))

    now = datetime.now(UTC)
    intent = await store.claim_standing_check_sync(now=now, lease_seconds=120.0)
    assert intent is not None
    assert intent.status is CheckSyncStatus.IN_PROGRESS
    assert intent.attempt_count == 1

    # A live lease is not reclaimable; an expired one is.
    assert await store.claim_standing_check_sync(now=now, lease_seconds=120.0) is None
    from datetime import timedelta

    reclaimed = await store.claim_standing_check_sync(
        now=now + timedelta(seconds=121), lease_seconds=120.0
    )
    assert reclaimed is not None
    assert reclaimed.intent_id == intent.intent_id

    await store.mark_standing_check_sync(intent.intent_id, status=CheckSyncStatus.PUBLISHED)
    latest = await store.latest_standing_check_sync(attempt_id=attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.PUBLISHED
    assert (await store.list_pending_standing_check_syncs(now=now + timedelta(hours=1))) == ()


@pytest.mark.asyncio
async def test_postgres_only_newest_revision_is_delivered(store: Any) -> None:
    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)
    await store.apply_finding_bypass(
        **_bypass_kwargs(attempt_id, request_key, blocking_fingerprints=("fp-1", "fp-2"))
    )
    # A second finding bypass supersedes the first intent (higher revision).
    await store.apply_finding_bypass(
        **_bypass_kwargs(
            attempt_id,
            request_key,
            finding_fingerprint="fp-2",
            blocking_fingerprints=("fp-1", "fp-2"),
            reason="second risk accepted",
        )
    )

    now = datetime.now(UTC)
    claimed = await store.claim_standing_check_sync(now=now, lease_seconds=120.0)
    assert claimed is not None
    latest = await store.latest_standing_check_sync(attempt_id=attempt_id)
    assert claimed.standing_revision == latest.standing_revision  # type: ignore[union-attr]
    # The first intent is terminal-superseded and never delivered.
    assert await store.claim_standing_check_sync(now=now, lease_seconds=120.0) is None


@pytest.mark.asyncio
async def test_postgres_bypass_and_retry_concurrently_no_deadlock(store: Any) -> None:
    """bypass x retry x publish cross the same advisory lock; every ordering
    converges without deadlock or torn state (P3 §5.3)."""

    locator = _locator()
    request_key = _request_key()
    attempt_id = await _standing_blocked_attempt(store, locator, request_key)

    async def _bypass() -> str:
        try:
            await store.apply_finding_bypass(**_bypass_kwargs(attempt_id, request_key))
            return "applied"
        except StateConflictError:
            return "rejected"

    async def _retry() -> None:
        await store.start_authoritative_attempt(change_request=locator, request_key=request_key)

    outcomes = await asyncio.gather(*[_bypass() for _ in range(3)], *[_retry() for _ in range(3)])
    bypass_outcomes = outcomes[:3]
    assert all(outcome in ("applied", "rejected") for outcome in bypass_outcomes)
    records = await store.list_bypasses(attempt_id=attempt_id)
    # The unique constraint admits at most one record (later identical calls
    # are replays); whatever landed was invalidated by the retry that took
    # authority.
    assert len(records) <= 1
    assert all(record.status is BypassStatus.INVALIDATED for record in records)
    current = await store.get_change_request_state(locator)
    assert current.authoritative_attempt_id != attempt_id
