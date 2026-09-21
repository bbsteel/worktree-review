"""Session Insight integration status and probing (Worktree Review side).

Four honest states: connected / disconnected / incompatible / disabled.
The probe is a real HTTP call to the Session Insight ``/api/agents``
catalog; "connected" requires the merged ``worktree-review`` reader to be
present. Session Insight is advisory observation only — a failure here never
touches the Review Gate.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

READER_AGENT_TYPE = "worktree-review"
PROBE_TIMEOUT_SECONDS = 2.0
PROBE_CACHE_SECONDS = 15.0


class SessionInsightState(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    INCOMPATIBLE = "incompatible"
    DISABLED = "disabled"


@dataclass(frozen=True)
class SessionInsightProbeResult:
    state: SessionInsightState
    base_url: str | None
    probed_at: str | None
    detail: str
    reader_revision: str | None = None


def session_insight_base_url_from_environment(
    environ: dict[str, str] | None = None,
) -> str | None:
    """Trusted, deployment-configured Session Insight base URL (http/https only)."""

    env = os.environ if environ is None else environ
    raw = env.get("WORKTREE_REVIEW_SESSION_INSIGHT_URL", "").strip()
    if not raw:
        return None
    parsed = httpx.URL(raw)
    if parsed.scheme not in ("http", "https") or not parsed.host:
        return None
    return raw.rstrip("/")


def session_insight_disabled_from_environment(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("WORKTREE_REVIEW_SESSION_INSIGHT_DISABLED", "").lower() in {"1", "true", "yes"}


class SessionInsightMonitor:
    """Cached probe of the configured Session Insight deployment."""

    def __init__(
        self,
        *,
        base_url: str | None,
        disabled: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._disabled = disabled
        self._http_client = http_client
        self._cached: SessionInsightProbeResult | None = None
        self._cached_at: datetime | None = None

    @property
    def base_url(self) -> str | None:
        return self._base_url

    async def current(self) -> SessionInsightProbeResult:
        now = datetime.now(UTC)
        if (
            self._cached is not None
            and self._cached_at is not None
            and (now - self._cached_at).total_seconds() < PROBE_CACHE_SECONDS
        ):
            return self._cached
        result = await self._probe(now)
        self._cached = result
        self._cached_at = now
        return result

    async def _probe(self, now: datetime) -> SessionInsightProbeResult:
        probed_at = now.isoformat()
        if self._disabled:
            return SessionInsightProbeResult(
                state=SessionInsightState.DISABLED,
                base_url=self._base_url,
                probed_at=probed_at,
                detail="Session Insight observation is disabled by configuration.",
            )
        if self._base_url is None:
            return SessionInsightProbeResult(
                state=SessionInsightState.DISCONNECTED,
                base_url=None,
                probed_at=probed_at,
                detail="WORKTREE_REVIEW_SESSION_INSIGHT_URL is not configured.",
            )
        try:
            if self._http_client is not None:
                response = await self._http_client.get(
                    f"{self._base_url}/api/agents", timeout=PROBE_TIMEOUT_SECONDS
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self._base_url}/api/agents", timeout=PROBE_TIMEOUT_SECONDS
                    )
        except Exception as exc:
            return SessionInsightProbeResult(
                state=SessionInsightState.DISCONNECTED,
                base_url=self._base_url,
                probed_at=probed_at,
                detail=f"Session Insight is unreachable: {exc.__class__.__name__}",
            )
        if response.status_code != 200:
            return SessionInsightProbeResult(
                state=SessionInsightState.DISCONNECTED,
                base_url=self._base_url,
                probed_at=probed_at,
                detail=f"Session Insight answered HTTP {response.status_code}.",
            )
        try:
            agents: Any = response.json()
        except ValueError:
            agents = None
        if not isinstance(agents, list):
            return SessionInsightProbeResult(
                state=SessionInsightState.INCOMPATIBLE,
                base_url=self._base_url,
                probed_at=probed_at,
                detail="Session Insight /api/agents did not return a reader catalog.",
            )
        for entry in agents:
            # Contract (session-insight GET /api/agents → AgentInfo):
            # {"type": "worktree-review", "adapter_revision": <int>, ...}
            if isinstance(entry, dict) and entry.get("type") == READER_AGENT_TYPE:
                revision = entry.get("adapter_revision")
                return SessionInsightProbeResult(
                    state=SessionInsightState.CONNECTED,
                    base_url=self._base_url,
                    probed_at=probed_at,
                    detail="Session Insight hosts the worktree-review reader.",
                    reader_revision=str(revision) if revision is not None else None,
                )
        return SessionInsightProbeResult(
            state=SessionInsightState.INCOMPATIBLE,
            base_url=self._base_url,
            probed_at=probed_at,
            detail="Session Insight is reachable but has no worktree-review reader.",
        )

    def deep_link(self, attempt_id: str) -> str | None:
        """Stable link from trusted configuration: #/session/worktree-review/<attempt-id>."""
        if self._base_url is None:
            return None
        return f"{self._base_url}/#/session/worktree-review/{attempt_id}"
