"""Background Attempt worker. HTTP handlers must not call this in-request."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.core.pipeline import ReviewRequest
from worktree_review.core.provider import UsageRecord, build_provider
from worktree_review.core.report import ReviewProgressEvent
from worktree_review.platform.cli.invocation import prepare_cli_review
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.web.runtime import WebRuntime


def _cost_fields(usage: tuple[UsageRecord, ...]) -> tuple[str | None, bool]:
    if not usage:
        return None, True
    measured = tuple(record for record in usage if record.cost_usd is not None)
    if not measured:
        return None, True
    total = sum(record.cost_usd for record in measured if record.cost_usd is not None)
    unknown = len(measured) != len(usage)
    return str(total), unknown


async def recover_interrupted(runtime: WebRuntime) -> None:
    for attempt_id in await runtime.store.list_incomplete_attempt_ids():
        run = await runtime.store.get_run(attempt_id)
        if run is None:
            continue
        if run.run_status is RunStatus.RUNNING:
            await runtime.store.mark_interrupted(attempt_id)
        if runtime.journal is not None:
            runtime.journal.backfill(await runtime.store.list_events(attempt_id))
        await runtime.enqueue(attempt_id)


async def execute_attempt(runtime: WebRuntime, attempt_id: str) -> None:
    runtime.pipeline_invocations += 1
    run = await runtime.store.get_run(attempt_id)
    if run is None or not run.request_json:
        return
    request_body = json.loads(run.request_json)
    repository = await runtime.store.get_repository(str(request_body.get("repository_id") or ""))
    review_row = await runtime.store.get_trusted_policy(
        "trusted_review_policies", str(request_body.get("review_policy_id") or "")
    )
    compute_row = await runtime.store.get_trusted_policy(
        "trusted_compute_policies", str(request_body.get("compute_policy_id") or "")
    )
    if repository is None or review_row is None or compute_row is None:
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
        return
    source = request_body.get("source") if isinstance(request_body.get("source"), dict) else {}
    kind = str(source.get("kind") or "local-worktree")
    target_raw = source.get("target_ref")
    proposed_raw = source.get("proposed_ref") if kind == "local-committed-ref" else None
    recent = source.get("commit_count") if kind == "local-recent-commits" else None
    await runtime.recorder.hydrate(attempt_id)
    try:
        prepared = await prepare_cli_review(
            repository=Path(repository["canonical_root"]),
            target_ref=target_raw if isinstance(target_raw, str) else None,
            proposed_ref=proposed_raw if isinstance(proposed_raw, str) else None,
            recent_commit_count=int(recent) if recent is not None else None,
            policy_path=Path(review_row["path"]),
            compute_policy_path=Path(compute_row["path"]),
        )
    except Exception as exc:
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
        await runtime.recorder.record(
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.failed",
            payload={"safe_detail": str(exc)},
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

    provider = (
        runtime.provider_factory(prepared.compute_policy, prepared.provider_configuration)
        if runtime.provider_factory is not None
        else build_provider(prepared.compute_policy, prepared.provider_configuration)
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
                provider_configuration=prepared.provider_configuration,
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
        await runtime.store.update_run_status(attempt_id, RunStatus.FAILED)
        await runtime.recorder.record(
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.failed",
            payload={"safe_detail": str(exc)},
        )
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
