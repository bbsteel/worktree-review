"""SSE replay then subscribe. Event id is the Attempt sequence."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from worktree_review.application.review_events import ReviewEvent
from worktree_review.platform.web.runtime import WebRuntime


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
                if event.event_type in {"attempt.completed", "attempt.failed"}:
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
            if item.event_type in {"attempt.completed", "attempt.failed"}:
                return
    finally:
        runtime.unsubscribe(attempt_id, live)
