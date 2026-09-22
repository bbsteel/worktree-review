"""Background Attempt worker. HTTP handlers must not call this in-request.

Every Attempt gets its own exception boundary: provider construction,
journal writes, event recording, and Pipeline failures mark that Attempt
failed with a safe error event, but never terminate the queue consumer —
later queued Attempts still run.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import (
    safe_error_payload,
    scrub_secret_content,
)
from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.core.pipeline import ReviewRequest
from worktree_review.core.policy import is_builtin_review_policy_id
from worktree_review.core.provider import UsageRecord, build_provider
from worktree_review.core.report import ReviewProgressEvent
from worktree_review.platform.cli.invocation import prepare_cli_review
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.web.provider_resolution import (
    resolve_frozen_provider_configuration,
)
from worktree_review.platform.web.runtime import WebRuntime

logger = logging.getLogger(__name__)

_SAFE_DETAIL_LIMIT = 1024


def _safe_detail(exc: BaseException) -> str:
    """Bound and scrub the error text persisted on a failed Attempt."""

    detail = scrub_secret_content(str(exc) or exc.__class__.__name__)
    if len(detail) > _SAFE_DETAIL_LIMIT:
        return detail[:_SAFE_DETAIL_LIMIT] + "…"
    return detail


def _safe_failure_payload(exc: BaseException) -> dict[str, str]:
    """Typed, bounded, scrubbed failure payload (see review_events)."""
    return safe_error_payload(exc)


def _trusted_policy_drift(row: dict[str, Any], current_identity: Any) -> str | None:
    """None when the trusted file still matches the registered sha256 identity."""

    registered_sha256 = row.get("version_sha256")
    if registered_sha256 and registered_sha256 != current_identity.sha256:
        return (
            f"trusted policy drifted after registration: {row.get('path')} "
            f"(registered sha256 {str(registered_sha256)[:12]}…, current "
            f"{current_identity.sha256[:12]}…); re-register the policy to adopt the change"
        )
    return None


def _cost_fields(usage: tuple[UsageRecord, ...]) -> tuple[str | None, bool]:
    if not usage:
        return None, True
    measured = tuple(record for record in usage if record.cost_usd is not None)
    if not measured:
        return None, True
    total = sum(record.cost_usd for record in measured if record.cost_usd is not None)
    unknown = len(measured) != len(usage)
    return str(total), unknown


async def _fail_attempt(runtime: WebRuntime, attempt_id: str, exc: BaseException) -> None:
    """Best-effort terminal failure marking; never raises into the consumer."""

    try:
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
    except Exception:
        logger.exception("failed to mark attempt %s as failed", attempt_id)
    try:
        await runtime.recorder.record(
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.failed",
            payload=_safe_failure_payload(exc),
        )
    except Exception:
        logger.exception("failed to record failure event for attempt %s", attempt_id)


async def recover_interrupted(runtime: WebRuntime) -> None:
    for attempt_id in await runtime.store.list_incomplete_attempt_ids():
        try:
            run = await runtime.store.get_run(attempt_id)
            if run is None:
                continue
            if run.run_status is RunStatus.RUNNING:
                await runtime.store.mark_interrupted(attempt_id)
            if runtime.journal is not None:
                runtime.journal.backfill(await runtime.store.list_events(attempt_id))
            # A crashed process may have been mid-Pipeline; re-execution can
            # repeat provider calls. Say so explicitly instead of silently
            # re-billing (results are immutable and never overwritten).
            await runtime.recorder.hydrate(attempt_id)
            await runtime.recorder.record(
                attempt_id=attempt_id,
                surface="web",
                event_type="attempt.resumed_after_restart",
                payload={
                    "safe_detail": (
                        "Attempt is re-executed after a server restart; provider "
                        "calls may be repeated and billed again. Prior results "
                        "are immutable and are never overwritten."
                    )
                },
            )
            await runtime.enqueue(attempt_id)
        except Exception:
            logger.exception("failed to recover interrupted attempt %s", attempt_id)


async def execute_attempt(runtime: WebRuntime, attempt_id: str) -> None:
    runtime.pipeline_invocations += 1
    try:
        await _execute_attempt_inner(runtime, attempt_id)
    except Exception as exc:
        await _fail_attempt(runtime, attempt_id, exc)


async def _execute_attempt_inner(runtime: WebRuntime, attempt_id: str) -> None:
    run = await runtime.store.get_run(attempt_id)
    if run is None or not run.request_json:
        return
    request_body = json.loads(run.request_json)
    repository = await runtime.store.get_repository(str(request_body.get("repository_id") or ""))
    review_policy_id = str(request_body.get("review_policy_id") or "")
    uses_builtin_review_policy = is_builtin_review_policy_id(review_policy_id)
    review_row = (
        None
        if uses_builtin_review_policy
        else await runtime.store.get_trusted_policy("trusted_review_policies", review_policy_id)
    )
    compute_row = await runtime.store.get_trusted_policy(
        "trusted_compute_policies", str(request_body.get("compute_policy_id") or "")
    )
    if (
        repository is None
        or (review_row is None and not uses_builtin_review_policy)
        or compute_row is None
    ):
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
        await runtime.recorder.record(
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.failed",
            payload={
                "category": "configuration",
                "safe_detail": "registered repository or trusted policy is missing",
            },
        )
        return
    source = request_body.get("source") if isinstance(request_body.get("source"), dict) else {}
    kind = str(source.get("kind") or "local-worktree")
    target_raw = source.get("target_ref")
    proposed_raw = source.get("proposed_ref") if kind == "local-committed-ref" else None
    recent = source.get("commit_count") if kind == "local-recent-commits" else None
    await runtime.recorder.hydrate(attempt_id)
    compute_path = Path(compute_row["path"])
    compute_source_format = compute_row.get("source_format") or "compute-policy"
    # Built-in Review Policy has no trusted file; prepare_cli_review loads it when
    # policy_path is None.
    review_policy_path = None if review_row is None else Path(review_row["path"])
    try:
        if compute_source_format == "user-config":
            prepared = await prepare_cli_review(
                repository=Path(repository["canonical_root"]),
                target_ref=target_raw if isinstance(target_raw, str) else None,
                proposed_ref=proposed_raw if isinstance(proposed_raw, str) else None,
                recent_commit_count=int(recent) if recent is not None else None,
                policy_path=review_policy_path,
                config_path=compute_path,
            )
        else:
            prepared = await prepare_cli_review(
                repository=Path(repository["canonical_root"]),
                target_ref=target_raw if isinstance(target_raw, str) else None,
                proposed_ref=proposed_raw if isinstance(proposed_raw, str) else None,
                recent_commit_count=int(recent) if recent is not None else None,
                policy_path=review_policy_path,
                compute_policy_path=compute_path,
            )
    except Exception as exc:
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
        await runtime.recorder.record(
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.failed",
            payload=safe_error_payload(exc),
        )
        return
    # Fail closed when a trusted policy file changed after registration:
    # the registered sha256 is the frozen identity the user reviewed.
    # Built-in Review Policy is product-owned and has no path-based drift check.
    review_drift = (
        None
        if review_row is None
        else _trusted_policy_drift(review_row, prepared.review_policy_version)
    )
    drift = review_drift or _trusted_policy_drift(compute_row, prepared.compute_policy_version)
    if drift is not None:
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
        await runtime.recorder.record(
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.failed",
            payload={"category": "policy-drift", "safe_detail": drift},
        )
        return
    await runtime.store.update_run_status(attempt_id, RunStatus.RUNNING)
    progress_queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    def on_progress(progress: ReviewProgressEvent) -> None:
        progress_queue.put_nowait(
            runtime.recorder.map_progress(progress, attempt_id=attempt_id, surface="web")
        )

    async def _drain_progress() -> None:
        while True:
            item = await progress_queue.get()
            if item is None:
                return
            event_type, payload = item
            await runtime.recorder.record(
                attempt_id=attempt_id,
                surface="web",
                event_type=event_type,
                payload=payload,
            )

    # Provider construction happens inside the per-Attempt boundary: the
    # frozen Provider Profile snapshot is resolved to a ProviderConfiguration
    # here, server-side, including its credential reference. Legacy rows
    # without a frozen snapshot keep the CLI-derived configuration.
    provider_configuration = resolve_frozen_provider_configuration(
        run.frozen_provider_json,
        compute_policy=prepared.compute_policy,
    )
    if provider_configuration is None:
        provider_configuration = prepared.provider_configuration
    provider = (
        runtime.provider_factory(prepared.compute_policy, provider_configuration)
        if runtime.provider_factory is not None
        else build_provider(prepared.compute_policy, provider_configuration)
    )
    drainer = asyncio.create_task(_drain_progress())

    async def _journal_heartbeat() -> None:
        while True:
            await asyncio.sleep(runtime.sse_heartbeat_seconds)
            if runtime.journal is not None:
                runtime.journal.touch_heartbeat(attempt_id)

    heartbeat = asyncio.create_task(_journal_heartbeat())
    try:
        report = await ReviewApplicationService().execute(
            ReviewRequest(
                resolved=prepared.resolved,
                review_policy=prepared.review_policy,
                review_policy_version=prepared.review_policy_version,
                compute_policy=prepared.compute_policy,
                compute_policy_version=prepared.compute_policy_version,
                surface="web",
                provider_configuration=provider_configuration,
            ),
            repository_path=prepared.repository_path,
            attempt_id=attempt_id,
            provider=provider,
            on_progress=on_progress,
        )
    except Exception as exc:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await progress_queue.put(None)
        await drainer
        await _fail_attempt(runtime, attempt_id, exc)
        return
    heartbeat.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await heartbeat
    await progress_queue.put(None)
    await drainer
    cost_usd, cost_unknown = _cost_fields(report.usage)
    await runtime.store.save_result(report, cost_usd=cost_usd, cost_unknown=cost_unknown)
    if runtime.journal is not None:
        runtime.journal.write_result(
            attempt_id, cli_result_document(report).model_dump_json(by_alias=True)
        )
    await runtime.recorder.record(
        attempt_id=attempt_id,
        surface="web",
        event_type="attempt.completed",
        payload={"gate_state": report.gate_state.value},
    )
