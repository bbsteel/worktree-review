"""Versioned ReviewEvent envelope. ``worktree-review.event/v1``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

EVENT_SCHEMA = "worktree-review.event/v1"
SurfaceName = Literal["cli", "web", "github"]


class ReviewEvent(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema_name: Literal["worktree-review.event/v1"] = Field(
        default="worktree-review.event/v1", alias="schema"
    )
    sequence: int = Field(ge=1)
    occurred_at: datetime
    attempt_id: str
    surface: SurfaceName
    event_type: str
    payload: dict[str, Any]
    reconstructed: bool = False


class ReviewEventStore(Protocol):
    async def append(self, event: ReviewEvent) -> None: ...

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]: ...


class ReviewEventSink(Protocol):
    """Best-effort consumer. Failure must not roll back the authoritative store."""

    async def publish(self, event: ReviewEvent) -> None: ...


_SECRET_KEYS = frozenset({"api_key", "authorization", "token", "secret", "password", "credential"})


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_KEYS):
            redacted[key] = "[redacted]"
        elif isinstance(value, dict):
            redacted[key] = redact_payload(value)
        else:
            redacted[key] = value
    return redacted


def utc_now() -> datetime:
    return datetime.now(UTC)
