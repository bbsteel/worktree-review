"""Versioned ReviewEvent envelope. ``worktree-review.event/v1``."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from enum import StrEnum
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

# Content-level scrubbing: truncating str(exc) is NOT enough when an error
# message echoes a credential (provider banners, failed auth responses).
_SECRET_CONTENT_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)\S+"),
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
)

# Provider Profiles may reference ANY environment variable. Scrub values of
# every credential-named variable, not a fixed list.
_CREDENTIAL_NAME_PATTERN = re.compile(r"(?i)(key|token|secret|password|credential|authorization)")


def _credential_env_values() -> list[str]:
    values: list[str] = []
    for name, value in os.environ.items():
        if len(value) >= 8 and _CREDENTIAL_NAME_PATTERN.search(name):
            values.append(value)
    return values


def scrub_secret_content(text: str) -> str:
    """Remove credential-shaped content from error text destined for events/logs.

    Covers common token formats and the current values of any credential-named
    environment variable (Provider Profiles may reference arbitrary ones via
    ${ENV_VAR}).
    """
    scrubbed = text
    for pattern in _SECRET_CONTENT_PATTERNS:
        scrubbed = pattern.sub("[redacted]", scrubbed)
    for value in _credential_env_values():
        if value in scrubbed:
            scrubbed = scrubbed.replace(value, "[redacted]")
    return scrubbed


class SafeErrorCategory(StrEnum):
    """Typed categories for persisted attempt failure details."""

    PROVIDER = "provider"
    CONFIGURATION = "configuration"
    POLICY_DRIFT = "policy-drift"
    PIPELINE = "pipeline"
    INTERNAL = "internal"


def safe_error_category(exc: BaseException) -> SafeErrorCategory:
    """Classify an execution failure for the persisted safe error event."""
    from worktree_review.core.errors import (  # local import avoids a cycle
        InvalidInvocationError,
        PolicyValidationError,
        ProviderError,
    )

    if isinstance(exc, ProviderError):
        return SafeErrorCategory.PROVIDER
    if isinstance(exc, (InvalidInvocationError, PolicyValidationError)):
        return SafeErrorCategory.CONFIGURATION
    if "PolicyDriftError" in type(exc).__name__:
        return SafeErrorCategory.POLICY_DRIFT
    return SafeErrorCategory.INTERNAL


def safe_error_payload(exc: BaseException, *, detail: str | None = None) -> dict[str, str]:
    """Typed, bounded, scrubbed failure payload.

    INTERNAL errors get fixed text only — their arbitrary messages never reach
    events, journals, or the browser.
    """
    category = safe_error_category(exc)
    if category is SafeErrorCategory.INTERNAL:
        return {
            "category": category.value,
            "safe_detail": "internal error; see server logs",
        }
    raw = detail if detail is not None else str(exc)
    scrubbed = scrub_secret_content(raw or type(exc).__name__)
    if len(scrubbed) > 1024:
        scrubbed = scrubbed[:1024] + "…"
    return {"category": category.value, "safe_detail": scrubbed}


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_KEYS):
            redacted[key] = "[redacted]"
        elif isinstance(value, dict):
            redacted[key] = redact_payload(value)
        elif isinstance(value, (list, tuple)):
            redacted[key] = [
                redact_payload(item)
                if isinstance(item, dict)
                else scrub_secret_content(item)
                if isinstance(item, str)
                else item
                for item in value
            ]
        elif isinstance(value, str):
            redacted[key] = scrub_secret_content(value)
        else:
            redacted[key] = value
    return redacted


def utc_now() -> datetime:
    return datetime.now(UTC)
