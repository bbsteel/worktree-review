"""Immutable GitHub Attempt execution snapshot. Credentials never belong here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.identity import ReviewRequestKey
from worktree_review.server.state import GitHubChangeRequestLocator


class AttemptExecutionSnapshot(BaseModel):
    """Trusted inputs frozen before the worker is queued."""

    model_config = ConfigDict(frozen=True)

    attempt_id: str
    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey
    proposed_ref: str
    review_policy_semver: str
    review_policy_sha256: str
    compute_policy_semver: str
    compute_policy_sha256: str
    provider_profile_id: str | None = None
    delivery_id: str | None = None
    pull_request_title: str | None = None
    author_login: str | None = None

    @property
    def installation_id(self) -> int:
        return self.change_request.installation_id

    def as_public_dict(self) -> dict[str, Any]:
        dumped = self.model_dump(mode="json")
        for forbidden in ("token", "secret", "credential", "password", "authorization"):
            dumped.pop(forbidden, None)
        return dumped


class PublicationIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str
    check_run_id: int = Field(gt=0)
    intent: str
    payload: dict[str, Any]
    status: PublicationStatus = PublicationStatus.QUEUED
    last_error: str | None = None
    attempt_count: int = 0
