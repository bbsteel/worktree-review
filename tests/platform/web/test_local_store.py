from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.identity import (
    ProposedSource,
    ResolvedCommitPair,
    ReviewRequestKey,
)
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    ExecutionRecord,
    GateState,
    ReviewReport,
)
from worktree_review.platform.web.local_store import (
    IdempotencyConflictError,
    ResultImmutableError,
    SqliteReviewRunStore,
)


def _event(attempt_id: str, sequence: int = 1) -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=datetime.now(UTC),
        attempt_id=attempt_id,
        surface="web",
        event_type="attempt.created",
        payload={"source": "local-worktree"},
    )


async def _store(tmp_path):
    store = SqliteReviewRunStore(tmp_path / "review.sqlite")
    await store.migrate()
    return store


@pytest.mark.asyncio
async def test_create_attempt_is_idempotent_and_persists_first_event(tmp_path) -> None:
    store = await _store(tmp_path)
    first = await store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a1",
        idempotency_key="key-1",
        request_digest="digest-a",
        initial_event=_event("a1"),
    )
    again = await store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a-ignored",
        idempotency_key="key-1",
        request_digest="digest-a",
        initial_event=_event("a-ignored"),
    )
    assert first == again == "a1"
    events = await store.list_events("a1")
    assert len(events) == 1
    with pytest.raises(IdempotencyConflictError):
        await store.create_attempt_with_initial_event_and_idempotency(
            attempt_id="a2",
            idempotency_key="key-1",
            request_digest="digest-b",
            initial_event=_event("a2"),
        )


@pytest.mark.asyncio
async def test_retry_creates_a_new_attempt_and_result_is_immutable(
    tmp_path, git_repository, policy_dir
) -> None:
    store = await _store(tmp_path)
    await store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a1",
        idempotency_key="k1",
        request_digest="d1",
        initial_event=_event("a1"),
    )
    await store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a2",
        idempotency_key="k2",
        request_digest="d2",
        initial_event=_event("a2"),
    )
    _review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    report = ReviewReport(
        gate_state=GateState.PASSED,
        attempt_id="a1",
        request_key=ReviewRequestKey(
            source_repository="demo/local",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            review_policy_version=review_version,
        ),
        resolved=ResolvedCommitPair(
            source_repository="demo/local",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_ref="HEAD",
            proposed_head_oid="b" * 40,
            proposed_source=ProposedSource.COMMITTED_REF,
        ),
        merge_tree_oid="c" * 40,
        review_identity=None,
        review_policy_version=review_version,
        compute_policy_version=compute_version,
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider=compute_policy.provider,
            model=compute_policy.model,
            data_destination=compute_policy.data_destination,
            known_retention=compute_policy.known_retention,
        ),
        execution=ExecutionRecord(),
        summary="ok",
        error_detail=None,
    )
    await store.save_result(report, cost_usd="0.18", cost_unknown=False)
    with pytest.raises(ResultImmutableError):
        await store.save_result(report, cost_usd="0.18", cost_unknown=False)
    run = await store.get_run("a1")
    assert run is not None
    assert run.result_json is not None
    # The stored result is the canonical versioned document (PM-100): it must
    # validate against the CLI result schema, not leak internal report fields.
    import json

    import jsonschema

    from worktree_review.schemas import CLI_RESULT_SCHEMA_ID, load_schema

    jsonschema.validate(
        instance=json.loads(run.result_json), schema=load_schema(CLI_RESULT_SCHEMA_ID)
    )
    retry = await store.get_run("a2")
    assert retry is not None
    assert retry.result_json is None


@pytest.mark.asyncio
async def test_unknown_cost_is_not_stored_as_zero(tmp_path, policy_dir) -> None:
    store = await _store(tmp_path)
    await store.create_attempt_with_initial_event_and_idempotency(
        attempt_id="a3",
        idempotency_key="k3",
        request_digest="d3",
        initial_event=_event("a3"),
    )
    _review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    report = ReviewReport(
        gate_state=GateState.ERROR,
        attempt_id="a3",
        request_key=ReviewRequestKey(
            source_repository="demo/local",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_head_oid="b" * 40,
            review_policy_version=review_version,
        ),
        resolved=ResolvedCommitPair(
            source_repository="demo/local",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_ref="HEAD",
            proposed_head_oid="b" * 40,
        ),
        merge_tree_oid=None,
        review_identity=None,
        review_policy_version=review_version,
        compute_policy_version=compute_version,
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider=compute_policy.provider,
            model=compute_policy.model,
            data_destination=compute_policy.data_destination,
            known_retention=compute_policy.known_retention,
        ),
        execution=ExecutionRecord(),
        summary="error",
        error_detail="merge failed",
    )
    await store.save_result(report, cost_usd=None, cost_unknown=True)
    run = await store.get_run("a3")
    assert run is not None
    assert run.cost_usd is None
    assert run.cost_unknown is True
    aggregate = await store.overview_aggregate()
    assert aggregate.unknown_cost_record_count == 1
    assert aggregate.known_cost_usd == "0.00"
