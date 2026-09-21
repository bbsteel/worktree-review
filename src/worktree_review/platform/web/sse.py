"""SSE replay then subscribe. Event id is the Attempt sequence."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from worktree_review.application.review_events import ReviewEvent
from worktree_review.platform.web.runtime import WebRuntime

_TERMINAL_EVENTS = frozenset({"attempt.completed", "attempt.failed"})


class GitHubEventSource(Protocol):
    """The PostgreSQL GitHub event store, as seen by the SSE tailer."""

    async def list_review_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]: ...


async def iter_attempt_events(
    runtime: WebRuntime,
    attempt_id: str,
    *,
    last_event_id: str | None = None,
    since: int | None = None,
) -> AsyncIterator[ReviewEvent | None]:
    if since is not None:
        after = since
    elif last_event_id:
        after = int(last_event_id)
    else:
        after = 0
    live = runtime.subscribe(attempt_id)
    try:
        stored = await runtime.store.list_events(attempt_id)
        seen: set[int] = set()
        for event in stored:
            if event.sequence > after:
                seen.add(event.sequence)
                yield event
                if event.event_type in _TERMINAL_EVENTS:
                    return
        while True:
            try:
                item = await asyncio.wait_for(live.get(), timeout=runtime.sse_heartbeat_seconds)
            except TimeoutError:
                yield None
                continue
            if item is None:
                return
            if item.sequence in seen or item.sequence <= after:
                continue
            seen.add(item.sequence)
            yield item
            if item.event_type in _TERMINAL_EVENTS:
                return
    finally:
        runtime.unsubscribe(attempt_id, live)


async def iter_github_attempt_events(
    store: GitHubEventSource,
    attempt_id: str,
    *,
    last_event_id: str | None = None,
    since: int | None = None,
    poll_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[ReviewEvent | None]:
    """GitHub Attempts: replay persisted PostgreSQL events, then tail by polling.

    Polling is the explicit equivalent of the local subscribe path: the
    durable store is authoritative, so a reconnect with Last-Event-ID never
    loses events, and a terminal event always ends the stream.
    """
    if since is not None:
        after = since
    elif last_event_id:
        after = int(last_event_id)
    else:
        after = 0
    seen: set[int] = set()
    loop = asyncio.get_running_loop()
    last_emit = loop.time()
    while True:
        events = await store.list_review_events(attempt_id)
        for event in events:
            if event.sequence <= after or event.sequence in seen:
                continue
            seen.add(event.sequence)
            yield event
            if event.event_type in _TERMINAL_EVENTS:
                return
        now = loop.time()
        if now - last_emit >= heartbeat_seconds:
            last_emit = now
            yield None
        await asyncio.sleep(poll_seconds)
