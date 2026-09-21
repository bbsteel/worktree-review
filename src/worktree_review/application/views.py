"""Surface DTO. Core ReviewReport must not grow these fields."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.application.lifecycle import (
    Authority,
    BypassState,
    PublicationStatus,
    RunStatus,
    ViewGateState,
)


class ReviewActionCapabilityView(BaseModel):
    model_config = ConfigDict(frozen=True)

    visible: bool
    enabled: bool
    disabled_reason: str | None = None


class AvailableReviewActionsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    retry: ReviewActionCapabilityView
    bypass: ReviewActionCapabilityView
    open_check: ReviewActionCapabilityView
    open_session_insight: ReviewActionCapabilityView


class LocalReviewSourceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["local-worktree", "local-recent-commits", "local-committed-ref"]
    repository_display_name: str
    worktree_label: str | None = None
    target_ref: str | None = None
    proposed_ref: str | None = None
    snapshot_sha: str | None = None


class GitHubPullRequestSourceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["github-pull-request"] = "github-pull-request"
    repository_full_name: str
    pull_request_number: int
    pull_request_title: str
    author_login: str
    proposed_branch: str
    target_branch: str
    commit_sha: str
    check_url: str | None = None


ReviewSourceView = Annotated[
    LocalReviewSourceView | GitHubPullRequestSourceView,
    Field(discriminator="kind"),
]


class SurfaceProjection(BaseModel):
    """Platform facts the mapper may use. Never written back into ReviewReport."""

    model_config = ConfigDict(frozen=True)

    source: ReviewSourceView
    run_status: RunStatus
    authority: Authority
    publication_status: PublicationStatus
    bypass_state: BypassState
    session_insight_connected: bool = False
    github_actor_authenticated: bool = False
    # Server-computed Bypass preconditions (standing, publication, Check,
    # live write-class role, trusted frozen Policy). The UI must not invent
    # these; ``project_available_actions`` only ANDs them with gate state.
    bypass_preconditions_met: bool = False


class ReviewRunView(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str
    run_status: RunStatus
    gate_state: ViewGateState
    authority: Authority
    publication_status: PublicationStatus
    bypass_state: BypassState
    source: ReviewSourceView
    summary: str
    error_detail: str | None
    available_actions: AvailableReviewActionsView
