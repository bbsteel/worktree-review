from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.platform.github.checks import CheckRunPayload, CheckRunStatus
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.triggers import GitHubTriggerCoordinator
from worktree_review.platform.github.webhooks import GitHubWebhookEvent
from worktree_review.server.state import AttemptLease, InMemoryAuthoritativeAttemptStore


class _FakeChecks:
    def __init__(self) -> None:
        self.created: list[CheckRunPayload] = []
        self.next_id = 100

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        del repository
        self.created.append(payload)
        self.next_id += 1
        return self.next_id

    async def update_check_run(
        self, *, repository: str, check_run_id: int, payload: CheckRunPayload
    ) -> None:
        del repository, check_run_id, payload


class _FakeQueue:
    def __init__(self) -> None:
        self.leases: list[str] = []

    async def __call__(self, lease: AttemptLease) -> None:
        self.leases.append(lease.attempt_id)


def _pr_event(
    *,
    action: str,
    delivery_id: str = "d1",
    draft: bool = False,
    base_sha: str | None = None,
    head_sha: str | None = None,
    changes: dict[str, object] | None = None,
) -> GitHubWebhookEvent:
    payload: dict[str, object] = {
        "action": action,
        "installation": {"id": 7},
        "repository": {"full_name": "octo/example"},
        "pull_request": {
            "number": 42,
            "title": "Harden webhook",
            "draft": draft,
            "user": {"login": "ada"},
            "base": {"ref": "main", "sha": base_sha or "a" * 40},
            "head": {"ref": "feature", "sha": head_sha or "b" * 40},
        },
    }
    if changes is not None:
        payload["changes"] = changes
    return GitHubWebhookEvent(
        event_name="pull_request",
        delivery_id=delivery_id,
        action=action,
        payload=payload,
    )


async def _coordinator(policy_dir: Path):
    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    checks = _FakeChecks()
    queue = _FakeQueue()
    coordinator = GitHubTriggerCoordinator(
        state=state,
        github_store=store,
        checks=checks,
        enqueue_attempt=queue,
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
        provider_profile_id="profile-1",
    )
    return coordinator, state, store, checks, queue


@pytest.mark.asyncio
async def test_opened_persists_snapshot_and_queued_check_before_enqueue(policy_dir: Path) -> None:
    coordinator, _state, store, checks, queue = await _coordinator(policy_dir)
    result = await coordinator.handle(_pr_event(action="opened"))
    assert result.status == "accepted"
    assert result.attempt_id is not None
    snapshot = await store.get_execution_snapshot(result.attempt_id)
    assert snapshot is not None
    assert snapshot.provider_profile_id == "profile-1"
    assert "token" not in snapshot.as_public_dict()
    assert await store.get_check_run_id(result.attempt_id) == 101
    assert checks.created[0].status is CheckRunStatus.QUEUED
    assert queue.leases == [result.attempt_id]
    replay = await coordinator.handle(_pr_event(action="opened", delivery_id="d1"))
    assert replay.attempt_id == result.attempt_id
    assert len(queue.leases) == 1
    assert len(checks.created) == 1


@pytest.mark.asyncio
async def test_draft_and_retarget_and_target_push_invalidate_standing(policy_dir: Path) -> None:
    coordinator, state, _store, _checks, _queue = await _coordinator(policy_dir)
    started = await coordinator.handle(_pr_event(action="opened", delivery_id="open-1"))
    assert started.attempt_id is not None
    draft = await coordinator.handle(_pr_event(action="converted_to_draft", delivery_id="draft-1"))
    assert draft.status == "invalidated"
    events = await state.audit_events()
    assert any(event["event_type"] == "standing_decision_invalidated" for event in events)
    retarget = await coordinator.handle(
        _pr_event(
            action="edited",
            delivery_id="edit-1",
            changes={"base": {"from": {"ref": "main", "sha": "a" * 40}}},
        )
    )
    assert retarget.status in {"invalidated", "accepted"}
    push = GitHubWebhookEvent(
        event_name="push",
        delivery_id="push-1",
        action=None,
        payload={
            "ref": "refs/heads/main",
            "repository": {"full_name": "octo/example"},
            "installation": {"id": 7},
        },
    )
    pushed = await coordinator.handle(push)
    assert pushed.status in {"invalidated", "ignored"}
