"""Authoritative GitHub worker: claim, restore snapshot, run shared Pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from worktree_review.application.event_recorder import ReviewEventRecorder
from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.core.identity import ProposedSource, ResolvedCommitPair
from worktree_review.core.pipeline import ReviewRequest
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.provider import ProviderClient
from worktree_review.core.report import ReviewProgressEvent, ReviewReport
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.github.checks import (
    CheckRunTransport,
    build_in_progress_check_run_payload,
)
from worktree_review.platform.github.mirrors import RepositoryMirrorManager
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.server.state import AuthoritativeAttemptStore

CloneUrlResolver = Callable[[AttemptExecutionSnapshot], Awaitable[str]]
ProviderFactory = Callable[[AttemptExecutionSnapshot], ProviderClient]


class PolicyDriftError(RuntimeError):
    """Trusted policy files no longer match the frozen execution snapshot."""


class GitHubReviewWorker:
    def __init__(
        self,
        *,
        state: AuthoritativeAttemptStore,
        github_store: GitHubReviewStore,
        mirrors: RepositoryMirrorManager,
        checks: CheckRunTransport,
        review_policy_path: Path,
        compute_policy_path: Path,
        resolve_clone_url: CloneUrlResolver,
        provider_factory: ProviderFactory,
        details_url: str | None = None,
    ) -> None:
        self._state = state
        self._github_store = github_store
        self._mirrors = mirrors
        self._checks = checks
        self._review_policy_path = review_policy_path
        self._compute_policy_path = compute_policy_path
        self._resolve_clone_url = resolve_clone_url
        self._provider_factory = provider_factory
        self._details_url = details_url
        self._recorder = ReviewEventRecorder(github_store)
        self.pipeline_invocations = 0

    async def execute_claimed_attempt(self, attempt_id: str) -> ReviewReport | None:
        lease = await self._state.claim_attempt_job(attempt_id)
        if lease is None:
            return None
        snapshot = await self._github_store.get_execution_snapshot(attempt_id)
        if snapshot is None:
            raise PolicyDriftError(f"missing execution snapshot for {attempt_id}")
        review_policy, review_version = load_review_policy(self._review_policy_path)
        compute_policy, compute_version = load_compute_policy(self._compute_policy_path)
        if (
            review_version.sha256 != snapshot.review_policy_sha256
            or compute_version.sha256 != snapshot.compute_policy_sha256
        ):
            raise PolicyDriftError("trusted policy identity drifted after snapshot freeze")
        check_run_id = await self._github_store.get_check_run_id(attempt_id)
        if check_run_id is not None:
            await self._checks.update_check_run(
                repository=lease.change_request.repository,
                check_run_id=check_run_id,
                payload=build_in_progress_check_run_payload(
                    attempt_id=attempt_id,
                    head_sha=snapshot.request_key.proposed_head_oid,
                    details_url=self._details_url,
                ),
            )
        clone_url = await self._resolve_clone_url(snapshot)
        repository_path = await self._mirrors.materialize(
            installation_id=snapshot.installation_id,
            repository_full_name=snapshot.change_request.repository,
            clone_url=clone_url,
            required_oids=(
                snapshot.request_key.target_head_oid,
                snapshot.request_key.proposed_head_oid,
            ),
        )
        self.pipeline_invocations += 1
        await self._recorder.hydrate(attempt_id)
        if not await self._github_store.list_events(attempt_id):
            await self._recorder.record(
                attempt_id=attempt_id,
                surface="github",
                event_type="attempt.created",
                payload={
                    "source": "github-pull-request",
                    "repository": snapshot.change_request.repository,
                    "pull_request_number": snapshot.change_request.pull_request_number,
                },
            )
        progress_queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        def on_progress(progress: ReviewProgressEvent) -> None:
            progress_queue.put_nowait(
                self._recorder.map_progress(progress, attempt_id=attempt_id, surface="github")
            )

        async def _drain_progress() -> None:
            while True:
                item = await progress_queue.get()
                if item is None:
                    return
                event_type, payload = item
                await self._recorder.record(
                    attempt_id=attempt_id,
                    surface="github",
                    event_type=event_type,
                    payload=payload,
                )

        drainer = asyncio.create_task(_drain_progress())
        try:
            report = await ReviewApplicationService().execute(
                ReviewRequest(
                    resolved=ResolvedCommitPair(
                        source_repository=snapshot.request_key.source_repository,
                        target_ref=snapshot.request_key.target_ref,
                        target_head_oid=snapshot.request_key.target_head_oid,
                        proposed_ref=snapshot.proposed_ref,
                        proposed_head_oid=snapshot.request_key.proposed_head_oid,
                        proposed_source=ProposedSource.COMMITTED_REF,
                    ),
                    review_policy=review_policy,
                    review_policy_version=review_version,
                    compute_policy=compute_policy,
                    compute_policy_version=compute_version,
                    surface="github",
                ),
                repository_path=repository_path,
                attempt_id=lease.attempt_id,
                provider=self._provider_factory(snapshot),
                on_progress=on_progress,
            )
        except Exception as exc:
            await progress_queue.put(None)
            await drainer
            await self._recorder.record(
                attempt_id=attempt_id,
                surface="github",
                event_type="attempt.failed",
                payload={"safe_detail": str(exc)},
            )
            raise
        await progress_queue.put(None)
        await drainer
        if report.review_identity is not None:
            await self._state.record_review_identity(
                attempt_id=lease.attempt_id, review_identity=report.review_identity
            )
        await self._github_store.save_review_result(
            attempt_id, cli_result_document(report).model_dump_json(by_alias=True)
        )
        await self._recorder.record(
            attempt_id=attempt_id,
            surface="github",
            event_type="attempt.completed",
            payload={"gate_state": report.gate_state.value},
        )
        return report
