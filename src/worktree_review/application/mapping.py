"""Deterministic ReviewRunView projection from Core ReviewReport + surface facts."""

from __future__ import annotations

from typing import Literal

from worktree_review.application.lifecycle import (
    Authority,
    PublicationStatus,
    ViewGateState,
    project_gate_state,
)
from worktree_review.application.views import (
    AvailableReviewActionsView,
    GitHubPullRequestSourceView,
    LocalReviewSourceView,
    ReviewActionCapabilityView,
    ReviewRunView,
    SurfaceProjection,
)
from worktree_review.core.identity import ProposedSource
from worktree_review.core.report import ReviewReport


def local_source_from_report(report: ReviewReport) -> LocalReviewSourceView:
    proposed_source = report.resolved.proposed_source
    kind: Literal["local-worktree", "local-recent-commits", "local-committed-ref"]
    if proposed_source is ProposedSource.CURRENT_WORKTREE_SNAPSHOT:
        kind = "local-worktree"
        worktree_label = "WORKTREE"
    else:
        kind = "local-committed-ref"
        worktree_label = None
    return LocalReviewSourceView(
        kind=kind,
        repository_display_name=report.resolved.source_repository,
        worktree_label=worktree_label,
        target_ref=report.resolved.target_ref,
        proposed_ref=report.resolved.proposed_ref,
        snapshot_sha=report.resolved.proposed_head_oid,
    )


def project_available_actions(
    *,
    gate_state: ViewGateState,
    surface: SurfaceProjection,
) -> AvailableReviewActionsView:
    local = surface.source.kind != "github-pull-request"
    terminal = gate_state in {
        ViewGateState.PASSED,
        ViewGateState.PASSED_WITH_BYPASS,
        ViewGateState.BLOCKED,
        ViewGateState.ERROR,
    }
    retry_reason = None
    retry_enabled = terminal
    if not terminal:
        retry_reason = "Retry is available after the current attempt reaches a terminal gate."
    if local:
        bypass = ReviewActionCapabilityView(
            visible=False,
            enabled=False,
            disabled_reason="Bypass is not available for local one-shot results.",
        )
        open_check = ReviewActionCapabilityView(
            visible=False,
            enabled=False,
            disabled_reason="GitHub Checks do not apply to local reviews.",
        )
        if not retry_enabled:
            retry_reason = retry_reason or "Retry creates a new local attempt."
    else:
        github_source = surface.source
        assert isinstance(github_source, GitHubPullRequestSourceView)
        bypass_enabled = (
            gate_state is ViewGateState.BLOCKED
            and surface.authority is Authority.AUTHORITATIVE
            and surface.github_actor_authenticated
        )
        bypass = ReviewActionCapabilityView(
            visible=True,
            enabled=bypass_enabled,
            disabled_reason=(
                None
                if bypass_enabled
                else "Bypass requires an authorized GitHub actor and a completed blocking review."
            ),
        )
        open_check = ReviewActionCapabilityView(
            visible=True,
            enabled=github_source.check_url is not None
            and surface.publication_status is PublicationStatus.PUBLISHED,
            disabled_reason=(
                None
                if github_source.check_url is not None
                else "GitHub Checks are not connected for this attempt."
            ),
        )
        retry_enabled = (
            terminal
            and surface.authority is Authority.AUTHORITATIVE
            and surface.github_actor_authenticated
        )
        if not retry_enabled:
            retry_reason = (
                "GitHub Retry requires an authenticated actor and an authoritative attempt."
            )
    return AvailableReviewActionsView(
        retry=ReviewActionCapabilityView(
            visible=True,
            enabled=retry_enabled,
            disabled_reason=None if retry_enabled else retry_reason,
        ),
        bypass=bypass,
        open_check=open_check,
        open_session_insight=ReviewActionCapabilityView(
            visible=True,
            enabled=surface.session_insight_connected,
            disabled_reason=(
                None if surface.session_insight_connected else "Session Insight is not connected."
            ),
        ),
    )


def map_review_run(report: ReviewReport, surface: SurfaceProjection) -> ReviewRunView:
    gate_state = project_gate_state(report.gate_state)
    if (
        surface.authority is Authority.LOCAL_NON_AUTHORITATIVE
        and gate_state is ViewGateState.PASSED_WITH_BYPASS
    ):
        raise ValueError("local attempts cannot project Passed with bypass")
    return ReviewRunView(
        attempt_id=report.attempt_id,
        run_status=surface.run_status,
        gate_state=gate_state,
        authority=surface.authority,
        publication_status=surface.publication_status,
        bypass_state=surface.bypass_state,
        source=surface.source,
        summary=report.summary,
        error_detail=report.error_detail,
        available_actions=project_available_actions(gate_state=gate_state, surface=surface),
    )
