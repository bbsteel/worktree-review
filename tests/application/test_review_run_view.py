from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitutil import head_oid
from worktree_review.application.lifecycle import (
    Authority,
    BypassState,
    PublicationStatus,
    RunStatus,
    ViewGateState,
)
from worktree_review.application.mapping import local_source_from_report, map_review_run
from worktree_review.application.review_service import ReviewApplicationService
from worktree_review.application.views import GitHubPullRequestSourceView, SurfaceProjection
from worktree_review.core.identity import ResolvedCommitPair
from worktree_review.core.pipeline import ReviewRequest
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.provider import ScriptedProvider
from worktree_review.core.report import ReviewReport


async def _report(git_repository: Path, policy_dir: Path) -> ReviewReport:
    oid = head_oid(git_repository)
    review_policy, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    compute_policy, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    return await ReviewApplicationService().execute(
        ReviewRequest(
            resolved=ResolvedCommitPair(
                source_repository="acme/session-insight",
                target_ref="main",
                target_head_oid=oid,
                proposed_ref="HEAD",
                proposed_head_oid=oid,
            ),
            review_policy=review_policy,
            review_policy_version=review_version,
            compute_policy=compute_policy,
            compute_policy_version=compute_version,
            surface="web",
        ),
        repository_path=git_repository,
        attempt_id="attempt-view-1",
        provider=ScriptedProvider(payloads={"correctness": {"findings": []}}),
    )


@pytest.mark.asyncio
async def test_local_projection_keeps_axes_separate(git_repository: Path, policy_dir: Path) -> None:
    report = await _report(git_repository, policy_dir)
    source = local_source_from_report(report)
    view = map_review_run(
        report,
        SurfaceProjection(
            source=source,
            run_status=RunStatus.COMPLETED,
            authority=Authority.LOCAL_NON_AUTHORITATIVE,
            publication_status=PublicationStatus.NOT_APPLICABLE,
            bypass_state=BypassState.NONE,
        ),
    )
    assert view.attempt_id == report.attempt_id
    assert view.run_status is RunStatus.COMPLETED
    assert view.gate_state is ViewGateState.PASSED
    assert view.authority is Authority.LOCAL_NON_AUTHORITATIVE
    assert view.publication_status is PublicationStatus.NOT_APPLICABLE
    assert view.bypass_state is BypassState.NONE
    assert view.source.kind == "local-committed-ref"
    assert view.available_actions.bypass.visible is False
    assert view.available_actions.retry.visible is True


@pytest.mark.asyncio
async def test_github_fields_stay_on_the_surface_not_the_core_report(
    git_repository: Path, policy_dir: Path
) -> None:
    report = await _report(git_repository, policy_dir)
    assert "pull_request" not in ReviewReport.model_fields
    assert "author" not in ReviewReport.model_fields
    assert "check_url" not in ReviewReport.model_fields
    view = map_review_run(
        report,
        SurfaceProjection(
            source=GitHubPullRequestSourceView(
                repository_full_name="acme/payment-service",
                pull_request_number=184,
                pull_request_title="Harden webhook authorization",
                author_login="ada",
                proposed_branch="feature/webhook-auth",
                target_branch="main",
                commit_sha="c" * 40,
                check_url=None,
            ),
            run_status=RunStatus.COMPLETED,
            authority=Authority.AUTHORITATIVE,
            publication_status=PublicationStatus.NOT_APPLICABLE,
            bypass_state=BypassState.NONE,
        ),
    )
    assert view.source.kind == "github-pull-request"
    assert view.available_actions.bypass.visible is True
    assert view.available_actions.bypass.enabled is False
    assert view.available_actions.open_check.visible is True
    dumped = report.model_dump()
    assert "pull_request_number" not in dumped
    assert "author_login" not in dumped
