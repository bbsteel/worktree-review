"""Immutable GitHub Attempt execution snapshot. Credentials never belong here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.identity import ReviewRequestKey
from worktree_review.server.state import GitHubChangeRequestLocator


class AttemptExecutionSnapshot(BaseModel):
    """Trusted inputs frozen before the worker is queued.

    The policy *documents* are frozen alongside their identities so an older
    Attempt can always resume from its immutable snapshot — a later edit to
    the trusted policy files must neither change nor strand it. Snapshots
    written before this field existed fall back to the trusted-file path with
    a drift check.
    """

    model_config = ConfigDict(frozen=True)

    attempt_id: str
    change_request: GitHubChangeRequestLocator
    request_key: ReviewRequestKey
    proposed_ref: str
    review_policy_semver: str
    review_policy_sha256: str
    compute_policy_semver: str
    compute_policy_sha256: str
    review_policy_document: dict[str, Any] | None = None
    compute_policy_document: dict[str, Any] | None = None
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


_SECRET_SHAPED_KEYS = frozenset(
    {"token", "secret", "credential", "password", "authorization", "api_key", "key"}
)


def assert_document_secret_free(document: Any, *, path: str) -> None:
    """Recursively reject secret-shaped keys before freezing a policy document."""
    if isinstance(document, dict):
        for key, value in document.items():
            if str(key).lower() in _SECRET_SHAPED_KEYS:
                raise ValueError(f"policy document contains a secret-shaped key at {path}")
            assert_document_secret_free(value, path=f"{path}.{key}")
    elif isinstance(document, list):
        for index, item in enumerate(document):
            assert_document_secret_free(item, path=f"{path}[{index}]")


class PublicationIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str
    check_run_id: int = Field(gt=0)
    intent: str
    payload: dict[str, Any]
    status: PublicationStatus = PublicationStatus.QUEUED
    last_error: str | None = None
    attempt_count: int = 0
    next_retry_at: datetime | None = None
