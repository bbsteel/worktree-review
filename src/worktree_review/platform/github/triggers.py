"""GitHub PR/push trigger coordinator. Snapshot and queued Check exist before enqueue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from worktree_review.core.identity import ReviewRequestKey
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.platform.github.checks import CheckRunTransport, build_queued_check_run_payload
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.retry import AttemptEnqueuer
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.github.webhooks import GitHubWebhookEvent, WebhookDispatchResult
from worktree_review.server.state import (
    AttemptLease,
    AuthoritativeAttemptStore,
    GitHubChangeRequestLocator,
)

_START_ACTIONS = frozenset({"opened", "reopened", "synchronize", "ready_for_review"})


class GitHubTriggerCoordinator:
    def __init__(
        self,
        *,
        state: AuthoritativeAttemptStore,
        github_store: GitHubReviewStore,
        checks: CheckRunTransport,
        enqueue_attempt: AttemptEnqueuer | None,
        review_policy_path: Path,
        compute_policy_path: Path,
        provider_profile_id: str | None = None,
        details_url: str | None = None,
    ) -> None:
        self._state = state
        self._github_store = github_store
        self._checks = checks
        self._enqueue_attempt = enqueue_attempt
        self._review_policy_path = review_policy_path
        self._compute_policy_path = compute_policy_path
        self._provider_profile_id = provider_profile_id
        self._details_url = details_url

    async def handle(self, event: GitHubWebhookEvent) -> WebhookDispatchResult:
        if event.event_name == "push":
            return await self._handle_push(event)
        if event.event_name == "pull_request":
            return await self._handle_pull_request(event)
        return WebhookDispatchResult(
            status="ignored",
            event_name=event.event_name,
            detail="event is not a GitHub review trigger",
        )

    async def _handle_push(self, event: GitHubWebhookEvent) -> WebhookDispatchResult:
        payload = event.payload
        repository = _object(payload, "repository").get("full_name")
        ref = payload.get("ref")
        if not isinstance(repository, str) or not isinstance(ref, str):
            return WebhookDispatchResult(status="ignored", detail="push payload missing ref")
        branch = ref.removeprefix("refs/heads/")
        count = await self._state.invalidate_standing_for_target(
            repository=repository,
            target_ref=branch,
            reason="target branch push",
        )
        return WebhookDispatchResult(
            status="invalidated" if count else "ignored",
            event_name="push",
            detail=f"invalidated {count} standing decision(s) after target branch push",
        )

    async def _handle_pull_request(self, event: GitHubWebhookEvent) -> WebhookDispatchResult:
        action = event.action or ""
        payload = event.payload
        pull_request = _object(payload, "pull_request")
        locator = _locator_from_pull_request(payload)
        if action == "converted_to_draft":
            await self._state.invalidate_standing_decision(locator, reason="converted_to_draft")
            return WebhookDispatchResult(
                status="invalidated",
                event_name=event.event_name,
                detail="standing decision revoked because the pull request is a draft",
            )
        if action == "edited" and "base" in _object(payload, "changes"):
            await self._state.invalidate_standing_decision(locator, reason="base retarget")
            if pull_request.get("draft") is True:
                return WebhookDispatchResult(
                    status="invalidated",
                    event_name=event.event_name,
                    detail="standing decision revoked after base retarget",
                )
            action = "synchronize"
        if action not in _START_ACTIONS:
            return WebhookDispatchResult(
                status="ignored",
                event_name=event.event_name,
                detail=f"pull_request action {action} does not start a review",
            )
        if pull_request.get("draft") is True:
            return WebhookDispatchResult(
                status="ignored",
                event_name=event.event_name,
                detail="draft pull requests are not reviewed",
            )
        return await self._start_attempt(event, locator, pull_request)

    async def _start_attempt(
        self,
        event: GitHubWebhookEvent,
        locator: GitHubChangeRequestLocator,
        pull_request: dict[str, Any],
    ) -> WebhookDispatchResult:
        review_policy, review_version = load_review_policy(self._review_policy_path)
        _compute_policy, compute_version = load_compute_policy(self._compute_policy_path)
        del review_policy
        base = _object(pull_request, "base")
        head = _object(pull_request, "head")
        request_key = ReviewRequestKey(
            source_repository=locator.repository,
            target_ref=str(base.get("ref") or "main"),
            target_head_oid=str(base.get("sha") or ""),
            proposed_head_oid=str(head.get("sha") or ""),
            review_policy_version=review_version,
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "action": event.action,
                    "base": request_key.target_head_oid,
                    "head": request_key.proposed_head_oid,
                    "policy": review_version.sha256,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        lease = await self._state.start_authoritative_attempt(
            change_request=locator,
            request_key=request_key,
            delivery_id=event.delivery_id,
        )
        if event.delivery_id:
            await self._github_store.record_webhook_idempotency(
                installation_id=locator.installation_id,
                delivery_id=event.delivery_id,
                attempt_id=lease.attempt_id,
                request_digest=digest,
            )
        existing_check = await self._github_store.get_check_run_id(lease.attempt_id)
        if lease.delivery_replayed and existing_check is not None:
            return WebhookDispatchResult(
                status="accepted",
                event_name=event.event_name,
                attempt_id=lease.attempt_id,
                detail="delivery was already processed",
            )
        snapshot = AttemptExecutionSnapshot(
            attempt_id=lease.attempt_id,
            change_request=locator,
            request_key=request_key,
            proposed_ref=str(head.get("ref") or "HEAD"),
            review_policy_semver=review_version.semver,
            review_policy_sha256=review_version.sha256,
            compute_policy_semver=compute_version.semver,
            compute_policy_sha256=compute_version.sha256,
            provider_profile_id=self._provider_profile_id,
            delivery_id=event.delivery_id,
            pull_request_title=str(pull_request.get("title") or "") or None,
            author_login=str(_object(pull_request, "user").get("login") or "") or None,
        )
        await self._github_store.save_execution_snapshot(snapshot)
        check_run_id = await self._checks.create_check_run(
            repository=locator.repository,
            payload=build_queued_check_run_payload(
                attempt_id=lease.attempt_id,
                head_sha=request_key.proposed_head_oid,
                details_url=self._details_url,
            ),
        )
        await self._github_store.set_check_run_id(lease.attempt_id, check_run_id)
        if self._enqueue_attempt is not None:
            await self._enqueue_attempt(lease)
        return WebhookDispatchResult(
            status="accepted",
            event_name=event.event_name,
            attempt_id=lease.attempt_id,
            detail="queued check saved before enqueue",
        )


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


class QueuedAttemptPreparer:
    """Create snapshot + queued Check after an Attempt exists and before enqueue."""

    def __init__(
        self,
        *,
        github_store: GitHubReviewStore,
        checks: CheckRunTransport,
        review_policy_path: Path,
        compute_policy_path: Path,
        provider_profile_id: str | None = None,
        details_url: str | None = None,
    ) -> None:
        self._github_store = github_store
        self._checks = checks
        self._review_policy_path = review_policy_path
        self._compute_policy_path = compute_policy_path
        self._provider_profile_id = provider_profile_id
        self._details_url = details_url

    async def __call__(self, lease: AttemptLease) -> None:
        if await self._github_store.get_check_run_id(lease.attempt_id) is not None:
            return
        _review_policy, review_version = load_review_policy(self._review_policy_path)
        _compute_policy, compute_version = load_compute_policy(self._compute_policy_path)
        del _review_policy, _compute_policy
        snapshot = AttemptExecutionSnapshot(
            attempt_id=lease.attempt_id,
            change_request=lease.change_request,
            request_key=lease.request_key,
            proposed_ref="HEAD",
            review_policy_semver=review_version.semver,
            review_policy_sha256=review_version.sha256,
            compute_policy_semver=compute_version.semver,
            compute_policy_sha256=compute_version.sha256,
            provider_profile_id=self._provider_profile_id,
        )
        await self._github_store.save_execution_snapshot(snapshot)
        check_run_id = await self._checks.create_check_run(
            repository=lease.change_request.repository,
            payload=build_queued_check_run_payload(
                attempt_id=lease.attempt_id,
                head_sha=lease.request_key.proposed_head_oid,
                details_url=self._details_url,
            ),
        )
        await self._github_store.set_check_run_id(lease.attempt_id, check_run_id)


def _locator_from_pull_request(payload: dict[str, Any]) -> GitHubChangeRequestLocator:
    repository = str(_object(payload, "repository").get("full_name") or "")
    installation_id = int(_object(payload, "installation").get("id") or 0)
    number = int(_object(payload, "pull_request").get("number") or 0)
    return GitHubChangeRequestLocator(
        installation_id=installation_id,
        repository=repository,
        pull_request_number=number,
    )
