"""In-process Web runtime: store, queue, recorder, and SSE subscribers."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from worktree_review.application.event_recorder import ReviewEventRecorder
from worktree_review.application.review_events import ReviewEvent
from worktree_review.core.config import ProviderConfiguration
from worktree_review.core.policy import ComputePolicy
from worktree_review.core.provider import ProviderClient
from worktree_review.platform.session_insight.journal import SessionJournalWriter
from worktree_review.platform.session_insight.status import (
    SessionInsightMonitor,
    session_insight_base_url_from_environment,
    session_insight_disabled_from_environment,
)
from worktree_review.platform.web.local_store import SqliteReviewRunStore

_SUBSCRIBER_BUFFER = 256

logger = logging.getLogger(__name__)


class WebRuntime:
    def __init__(self, store: SqliteReviewRunStore, *, csrf_token: str | None = None) -> None:
        self.store = store
        self.recorder = ReviewEventRecorder(store)
        # Per-process CSRF token for local Web mutations. The same-origin
        # frontend obtains it from GET /api/v1/csrf-bootstrap; it is never
        # persisted, logged, or embedded into the served HTML.
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers: dict[str, list[asyncio.Queue[ReviewEvent | None]]] = {}
        self.worker_task: asyncio.Task[None] | None = None
        self.execute_attempt: Callable[[str], Awaitable[None]] | None = None
        self.provider_factory: (
            Callable[[ComputePolicy, ProviderConfiguration | None], ProviderClient] | None
        ) = None
        self.pipeline_invocations = 0
        self.sse_heartbeat_seconds = 15.0
        self.journal: SessionJournalWriter | None = None
        self.session_insight = SessionInsightMonitor(base_url=None, disabled=True)

    def subscribe(self, attempt_id: str) -> asyncio.Queue[ReviewEvent | None]:
        queue: asyncio.Queue[ReviewEvent | None] = asyncio.Queue(maxsize=_SUBSCRIBER_BUFFER)
        self._subscribers.setdefault(attempt_id, []).append(queue)
        return queue

    def unsubscribe(self, attempt_id: str, queue: asyncio.Queue[ReviewEvent | None]) -> None:
        listeners = self._subscribers.get(attempt_id, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners:
            self._subscribers.pop(attempt_id, None)

    async def publish(self, event: ReviewEvent) -> None:
        await self.broadcast(event)

    async def broadcast(self, event: ReviewEvent) -> None:
        dropped: list[asyncio.Queue[ReviewEvent | None]] = []
        for queue in list(self._subscribers.get(event.attempt_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dropped.append(queue)
        for queue in dropped:
            self.unsubscribe(event.attempt_id, queue)
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def enqueue(self, attempt_id: str) -> None:
        await self.queue.put(attempt_id)

    async def run_worker(self) -> None:
        while True:
            attempt_id = await self.queue.get()
            if self.execute_attempt is None:
                continue
            try:
                await self.execute_attempt(attempt_id)
            except Exception:
                # A worker callback must never kill the queue consumer; the
                # Attempt itself is already marked failed inside its own
                # boundary, and later queued Attempts continue.
                logger.exception("attempt %s escaped its execution boundary", attempt_id)


async def open_web_runtime(
    database_path: Path,
    *,
    journal_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> WebRuntime:
    store = SqliteReviewRunStore(database_path)
    await store.migrate()
    runtime = WebRuntime(store)
    disabled = session_insight_disabled_from_environment(environ)
    base_url = session_insight_base_url_from_environment(environ)
    runtime.session_insight = SessionInsightMonitor(base_url=base_url, disabled=disabled)
    runtime.journal = None if disabled else SessionJournalWriter(journal_root)
    runtime.recorder = ReviewEventRecorder(
        store, sinks=tuple(sink for sink in (runtime, runtime.journal) if sink is not None)
    )
    return runtime
