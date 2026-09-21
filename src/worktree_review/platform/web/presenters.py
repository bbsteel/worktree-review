"""Map persisted runs to the /api/v1 Surface DTOs consumed by the frontend."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from worktree_review.application.lifecycle import (
    Authority,
    BypassState,
    PublicationStatus,
    RunStatus,
    ViewGateState,
    project_gate_state,
)
from worktree_review.application.mapping import local_source_from_report, project_available_actions
from worktree_review.application.projections import project_coverage, project_usage
from worktree_review.application.review_runs import OverviewAggregate, ReviewRunRecord
from worktree_review.application.views import GitHubPullRequestSourceView, SurfaceProjection
from worktree_review.core.findings import EvidenceBand, Finding, Severity
from worktree_review.core.gate import finding_blocks_under_policy
from worktree_review.core.policy import ComputePolicy, ReviewPolicy
from worktree_review.core.report import PIPELINE_STAGE_ORDER, ReviewReport, StageStatus
from worktree_review.platform.cli.result import load_review_report_from_cli_result
from worktree_review.platform.github.checks import github_check_run_url
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.web.local_store import SqliteReviewRunStore
from worktree_review.platform.web.registry import parse_credential_reference
from worktree_review.server.audit import AuditEvent
from worktree_review.server.state import (
    AuthoritativeChangeRequestState,
    BypassRecord,
    BypassStatus,
)


def _cost_number(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_request(run: ReviewRunRecord) -> dict[str, Any]:
    if not run.request_json:
        return {}
    loaded = json.loads(run.request_json)
    return loaded if isinstance(loaded, dict) else {}


def _source_from_request(request: dict[str, Any], display_name: str) -> dict[str, Any]:
    source = request.get("source")
    if not isinstance(source, dict):
        source = {"kind": "local-worktree"}
    kind = str(source.get("kind") or "local-worktree")
    return {
        "kind": kind,
        "repository_display_name": display_name,
        "worktree_label": "WORKTREE" if kind == "local-worktree" else None,
        "target_ref": source.get("target_ref"),
        "proposed_ref": source.get("proposed_ref"),
        "snapshot_sha": None,
    }


def _queued_gate(run: ReviewRunRecord) -> str:
    if run.run_status is RunStatus.INTERRUPTED:
        return ViewGateState.ERROR.value
    if run.run_status is RunStatus.FAILED:
        return ViewGateState.ERROR.value
    if run.run_status is RunStatus.COMPLETED and run.gate_state:
        mapped = {
            "Passed": ViewGateState.PASSED.value,
            "Passed with bypass": ViewGateState.PASSED_WITH_BYPASS.value,
            "Blocked": ViewGateState.BLOCKED.value,
            "Error": ViewGateState.ERROR.value,
        }
        return mapped.get(run.gate_state, ViewGateState.IN_PROGRESS.value)
    return ViewGateState.IN_PROGRESS.value


def _empty_pipeline() -> list[dict[str, Any]]:
    return [
        {"stage": stage.value, "status": "not-started", "elapsed_ms": None, "safe_error": None}
        for stage in PIPELINE_STAGE_ORDER
    ]


def _session_insight_action(state: str) -> dict[str, Any]:
    if state == "connected":
        return {"visible": True, "enabled": True, "disabled_reason": None}
    reasons = {
        "disabled": "Session Insight observation is disabled by configuration.",
        "incompatible": "Session Insight is reachable but lacks the worktree-review reader.",
    }
    return {
        "visible": True,
        "enabled": False,
        "disabled_reason": reasons.get(state, "Session Insight is not connected."),
    }


def _local_actions(
    *, terminal: bool, session_insight_state: str = "disconnected"
) -> dict[str, Any]:
    retry_reason = (
        None
        if terminal
        else "Retry is available after the current attempt reaches a terminal gate."
    )
    return {
        "retry": {
            "visible": True,
            "enabled": terminal,
            "disabled_reason": retry_reason,
        },
        "bypass": {
            "visible": False,
            "enabled": False,
            "disabled_reason": "Bypass is not available for local one-shot results.",
        },
        "open_check": {
            "visible": False,
            "enabled": False,
            "disabled_reason": "GitHub Checks do not apply to local reviews.",
        },
        "open_session_insight": _session_insight_action(session_insight_state),
    }


def _summary_dto(
    *,
    attempt_id: str,
    display_name: str,
    source: dict[str, Any],
    run_status: str,
    gate_state: str,
    created_at: datetime,
    finding_count: int = 0,
    highest_severity: str | None = None,
    duration_ms: int | None = None,
    cost_usd: float | None = None,
    cost_unknown: bool = False,
    provider: str = "unknown",
    model: str = "unknown",
    completed_at: str | None = None,
    authority: str = Authority.LOCAL_NON_AUTHORITATIVE.value,
    publication_status: str = PublicationStatus.NOT_APPLICABLE.value,
) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "repository_display_name": display_name,
        "source": source,
        "run_status": run_status,
        "gate_state": gate_state,
        "authority": authority,
        "publication_status": publication_status,
        "bypass_state": BypassState.NONE.value,
        "finding_count": finding_count,
        "highest_severity": highest_severity,
        "duration_ms": duration_ms,
        "cost_usd": cost_usd,
        "cost_unknown": cost_unknown,
        "provider": provider,
        "model": model,
        "created_at": created_at.isoformat(),
        "completed_at": completed_at,
    }


def _coverage_from_report(report: ReviewReport) -> dict[str, Any]:
    return project_coverage(report.coverage)


def _usage_from_report(report: ReviewReport) -> dict[str, Any]:
    return project_usage(report)


def _evidence_band_for_view(band: EvidenceBand) -> str:
    if band is EvidenceBand.INSUFFICIENT:
        return "insufficient"
    return "supported"


def _finding_dto(
    finding: Finding,
    *,
    blocking: bool,
    bypass_record: BypassRecord | None = None,
) -> dict[str, Any]:
    return {
        "fingerprint": finding.fingerprint,
        "severity": finding.severity.value,
        "evidence_band": _evidence_band_for_view(finding.evidence_band),
        "dimension_id": finding.dimension_id or "not-reported",
        "problem_statement": finding.problem_statement,
        "expected_impact": finding.expected_impact,
        "repair_guidance": finding.repair_guidance or "",
        "evidence_spans": [
            {
                "path": span.path,
                "start_line": span.start_line,
                "end_line": span.end_line,
                "source": span.source.value,
                "snapshot_identity": span.snapshot_identity or "",
                "change_kind": (
                    span.change_kind.value if span.change_kind is not None else "unknown"
                ),
                "quoted_text": span.quoted_text,
            }
            for span in finding.evidence_spans
        ],
        "blocking": blocking,
        # Read-only risk-acceptance projection (P3 §8.2); never hides the
        # finding itself, only explains who accepted it and when.
        "bypass_record": (
            None
            if bypass_record is None
            else {
                "status": bypass_record.status.value,
                "actor_id": bypass_record.actor_id,
                "actor_login": bypass_record.actor_login,
                "reason": bypass_record.reason,
                "created_at": bypass_record.created_at.isoformat(),
                "invalidation_reason": bypass_record.invalidation_reason,
            }
        ),
    }


def _pipeline_from_report(report: ReviewReport) -> list[dict[str, Any]]:
    by_stage = {outcome.stage: outcome for outcome in report.execution.outcomes}
    stages: list[dict[str, Any]] = []
    for stage in PIPELINE_STAGE_ORDER:
        outcome = by_stage.get(stage)
        if outcome is None:
            status = "not-started"
            detail = None
        elif outcome.status is StageStatus.COMPLETED:
            status = "completed"
            detail = outcome.detail
        elif outcome.status is StageStatus.FAILED:
            status = "failed"
            detail = outcome.detail
        else:
            status = "not-started"
            detail = outcome.detail
        stages.append(
            {
                "stage": stage.value,
                "status": status,
                "elapsed_ms": None,
                "safe_error": detail,
            }
        )
    return stages


def present_review_summary(
    run: ReviewRunRecord,
    *,
    display_name: str,
    provider: str = "unknown",
    model: str = "unknown",
) -> dict[str, Any]:
    request = _parse_request(run)
    source = _source_from_request(request, display_name)
    report = load_review_report_from_cli_result(run.result_json) if run.result_json else None
    if report is not None:
        source = local_source_from_report(report).model_dump()
        provider = report.compute_policy_disclosure.provider
        model = report.compute_policy_disclosure.model
        severities = [finding.severity.value for finding in report.findings]
        highest = (
            max(severities, key=["suggestion", "minor", "major", "critical"].index)
            if (severities)
            else None
        )
        gate_state = project_gate_state(report.gate_state).value
        return _summary_dto(
            attempt_id=run.attempt_id,
            display_name=display_name,
            source=source,
            run_status=run.run_status.value,
            gate_state=gate_state,
            created_at=run.created_at,
            finding_count=len(report.findings),
            highest_severity=highest,
            cost_usd=_cost_number(run.cost_usd),
            cost_unknown=run.cost_unknown,
            provider=provider,
            model=model,
            completed_at=run.created_at.isoformat() if run.result_json else None,
        )
    return _summary_dto(
        attempt_id=run.attempt_id,
        display_name=display_name,
        source=source,
        run_status=run.run_status.value,
        gate_state=_queued_gate(run),
        created_at=run.created_at,
        cost_usd=_cost_number(run.cost_usd),
        cost_unknown=run.cost_unknown,
        provider=provider,
        model=model,
    )


def present_review_run(
    run: ReviewRunRecord,
    *,
    display_name: str,
    review_policy: ReviewPolicy | None = None,
    compute_policy: ComputePolicy | None = None,
    session_insight_state: str = "disconnected",
    session_insight_deep_link: str | None = None,
) -> dict[str, Any]:
    request = _parse_request(run)
    source = _source_from_request(request, display_name)
    summary = present_review_summary(run, display_name=display_name)
    if run.result_json:
        report = load_review_report_from_cli_result(run.result_json)
        source_view = local_source_from_report(report)
        surface = SurfaceProjection(
            source=source_view,
            run_status=run.run_status,
            authority=Authority.LOCAL_NON_AUTHORITATIVE,
            publication_status=PublicationStatus.NOT_APPLICABLE,
            bypass_state=BypassState.NONE,
            session_insight_connected=session_insight_state == "connected",
        )
        actions = project_available_actions(
            gate_state=project_gate_state(report.gate_state),
            surface=surface,
        )
        blocking_severities = (
            review_policy.blocking_severities
            if review_policy is not None
            else (Severity.CRITICAL, Severity.MAJOR)
        )
        blocking = [
            finding.fingerprint
            for finding in report.findings
            if finding.severity in blocking_severities
            and finding.evidence_band is not EvidenceBand.INSUFFICIENT
        ]
        identity_unavailable = (
            None
            if report.review_identity is not None
            else "Review identity unavailable — merge candidate was not constructed."
        )
        dimensions = [
            {
                "dimension_id": outcome.dimension_id,
                "status": outcome.status.value,
                "elapsed_ms": None,
                "finding_count": sum(
                    1 for finding in report.findings if finding.dimension_id == outcome.dimension_id
                ),
                "blocking_finding_count": sum(
                    1
                    for finding in report.findings
                    if finding.dimension_id == outcome.dimension_id
                    and finding.fingerprint in blocking
                ),
            }
            for outcome in report.dimension_outcomes
        ]
        failed = next(
            (
                outcome
                for outcome in report.execution.outcomes
                if outcome.status is StageStatus.FAILED
            ),
            None,
        )
        return {
            "attempt_id": run.attempt_id,
            "run_status": run.run_status.value,
            "gate_state": project_gate_state(report.gate_state).value,
            "authority": Authority.LOCAL_NON_AUTHORITATIVE.value,
            "publication_status": PublicationStatus.NOT_APPLICABLE.value,
            "bypass_state": BypassState.NONE.value,
            "source": source_view.model_dump(),
            "summary": summary,
            "gate": {
                "gate_state": project_gate_state(report.gate_state).value,
                "blocking_fingerprints": blocking,
                "summary": report.summary,
                "required_coverage_complete": (
                    report.coverage.required_coverage_complete if report.coverage else False
                ),
            },
            "findings": [
                _finding_dto(
                    finding,
                    blocking=finding.severity in blocking_severities
                    and finding.evidence_band is not EvidenceBand.INSUFFICIENT,
                )
                for finding in report.findings
            ],
            "coverage": _coverage_from_report(report),
            "dimensions": dimensions,
            "pipeline": _pipeline_from_report(report),
            "failure": None
            if failed is None
            else {
                "stage": failed.stage.value,
                "category": "pipeline",
                "safe_detail": failed.detail or report.error_detail or "stage failed",
            },
            "attempts": [
                {
                    "attempt_id": run.attempt_id,
                    "authority": Authority.LOCAL_NON_AUTHORITATIVE.value,
                    "gate_state": project_gate_state(report.gate_state).value,
                    "trigger": "local-web",
                    "provider": report.compute_policy_disclosure.provider,
                    "model": report.compute_policy_disclosure.model,
                    "review_policy_version": report.review_policy_version.semver,
                    "compute_policy_version": report.compute_policy_version.semver,
                    "token_count": None,
                    "cost_usd": _cost_number(run.cost_usd),
                    "cost_unknown": run.cost_unknown,
                    "started_at": run.created_at.isoformat(),
                    "duration_ms": None,
                }
            ],
            "identity": {
                "review_request_key": (
                    f"{report.request_key.source_repository}:"
                    f"{report.request_key.target_ref}:"
                    f"{report.request_key.target_head_oid}:"
                    f"{report.request_key.proposed_head_oid}"
                ),
                "source_repository": report.resolved.source_repository,
                "target_ref": report.resolved.target_ref,
                "target_head_oid": report.resolved.target_head_oid,
                "proposed_source": report.resolved.proposed_source.value,
                "proposed_head_oid": report.resolved.proposed_head_oid,
                "merge_tree_oid": report.merge_tree_oid,
                "review_identity": (
                    None
                    if report.review_identity is None
                    else report.review_identity.candidate.merge_tree_oid
                ),
                "identity_unavailable_reason": identity_unavailable,
            },
            "policies": {
                "review_policy_name": "review-policy",
                "review_policy_version": report.review_policy_version.semver,
                "review_policy_sha256": report.review_policy_version.sha256,
                "compute_policy_name": "compute-policy",
                "compute_policy_version": report.compute_policy_version.semver,
                "compute_policy_sha256": report.compute_policy_version.sha256,
                "data_destination": report.compute_policy_disclosure.data_destination,
                "retention_disclosure": report.compute_policy_disclosure.known_retention,
                "provider_configuration_fingerprint": (
                    report.compute_policy_disclosure.provider_configuration_fingerprint
                ),
            },
            "usage": _usage_from_report(report),
            "provider_health": {
                "profile_name": report.compute_policy_disclosure.provider,
                "status": "not_tested",
                "observed_at": None,
            },
            "available_actions": actions.model_dump(),
            "session_insight_deep_link": session_insight_deep_link,
        }

    dimensions = [
        {
            "dimension_id": dimension_id,
            "status": "not-started",
            "elapsed_ms": None,
            "finding_count": 0,
            "blocking_finding_count": 0,
        }
        for dimension_id in (review_policy.required_dimensions if review_policy is not None else ())
    ]
    return {
        "attempt_id": run.attempt_id,
        "run_status": run.run_status.value,
        "gate_state": _queued_gate(run),
        "authority": Authority.LOCAL_NON_AUTHORITATIVE.value,
        "publication_status": PublicationStatus.NOT_APPLICABLE.value,
        "bypass_state": BypassState.NONE.value,
        "source": source,
        "summary": summary,
        "gate": {
            "gate_state": _queued_gate(run),
            "blocking_fingerprints": [],
            "summary": "Attempt queued",
            "required_coverage_complete": False,
        },
        "findings": [],
        "coverage": {
            "required_coverage": "incomplete",
            "reviewed_count": 0,
            "excluded_count": 0,
            "missing_count": 0,
            "files": [],
        },
        "dimensions": dimensions,
        "pipeline": _empty_pipeline(),
        "failure": None,
        "attempts": [
            {
                "attempt_id": run.attempt_id,
                "authority": Authority.LOCAL_NON_AUTHORITATIVE.value,
                "gate_state": _queued_gate(run),
                "trigger": "local-web",
                "provider": compute_policy.provider if compute_policy is not None else "unknown",
                "model": compute_policy.model if compute_policy is not None else "unknown",
                "review_policy_version": (
                    review_policy.version if review_policy is not None else "unknown"
                ),
                "compute_policy_version": (
                    compute_policy.version if compute_policy is not None else "unknown"
                ),
                "token_count": None,
                "cost_usd": None,
                "cost_unknown": True,
                "started_at": run.created_at.isoformat(),
                "duration_ms": None,
            }
        ],
        "identity": {
            "review_request_key": "pending",
            "source_repository": display_name,
            "target_ref": source.get("target_ref") or "HEAD",
            "target_head_oid": None,
            "proposed_source": source.get("kind") or "local-worktree",
            "proposed_head_oid": None,
            "merge_tree_oid": None,
            "review_identity": None,
            "identity_unavailable_reason": (
                "Review identity is assigned after merge construction."
            ),
        },
        "policies": {
            "review_policy_name": "review-policy",
            "review_policy_version": (
                review_policy.version if review_policy is not None else "unknown"
            ),
            "review_policy_sha256": "0" * 64,
            "compute_policy_name": "compute-policy",
            "compute_policy_version": (
                compute_policy.version if compute_policy is not None else "unknown"
            ),
            "compute_policy_sha256": "0" * 64,
            "data_destination": (
                compute_policy.data_destination if compute_policy is not None else "unknown"
            ),
            "retention_disclosure": (
                compute_policy.known_retention if compute_policy is not None else "unknown"
            ),
            "provider_configuration_fingerprint": (
                compute_policy.provider_configuration_fingerprint
                if compute_policy is not None
                else None
            ),
        },
        "usage": {
            "estimated_cost_usd": None,
            "actual_cost_usd": None,
            "cost_unknown": True,
            "unknown_cost_record_count": 0,
            "input_tokens": None,
            "output_tokens": None,
            "calls": [],
        },
        "provider_health": {
            "profile_name": compute_policy.provider if compute_policy is not None else "unknown",
            "status": "not_tested",
            "observed_at": None,
        },
        "available_actions": _local_actions(
            terminal=False, session_insight_state=session_insight_state
        ),
        "session_insight_deep_link": session_insight_deep_link,
    }


def github_source_view(
    snapshot: AttemptExecutionSnapshot, *, check_run_id: int | None
) -> GitHubPullRequestSourceView:
    locator = snapshot.change_request
    check_url = (
        None
        if check_run_id is None
        else github_check_run_url(repository=locator.repository, check_run_id=check_run_id)
    )
    return GitHubPullRequestSourceView(
        repository_full_name=locator.repository,
        pull_request_number=locator.pull_request_number,
        pull_request_title=snapshot.pull_request_title or "",
        author_login=snapshot.author_login or "",
        proposed_branch=snapshot.proposed_ref,
        target_branch=snapshot.request_key.target_ref,
        commit_sha=snapshot.request_key.proposed_head_oid,
        check_url=check_url,
    )


def github_authority_for_attempt(
    *,
    attempt_id: str,
    change_state: AuthoritativeChangeRequestState,
) -> Authority:
    if change_state.authoritative_attempt_id == attempt_id:
        return Authority.AUTHORITATIVE
    if change_state.standing_attempt_id == attempt_id:
        return Authority.AUTHORITATIVE
    return Authority.SUPERSEDED


def present_github_review_run(
    *,
    snapshot: AttemptExecutionSnapshot,
    change_state: AuthoritativeChangeRequestState,
    publication_status: PublicationStatus | None,
    check_run_id: int | None,
    result_json: str | None,
    created_at: datetime,
    session_insight_state: str = "disconnected",
    session_insight_deep_link: str | None = None,
    job_status: str | None = None,
    job_failure_detail: str | None = None,
    bypasses: tuple[BypassRecord, ...] = (),
    check_sync_status: str | None = None,
    bypass_capability: str = "unavailable",
    actor_authenticated: bool = False,
    bypass_preconditions_met: bool = False,
    blocking_policy: ReviewPolicy | None = None,
    review_policy_trusted: bool = False,
) -> dict[str, Any]:
    """Map a PostgreSQL GitHub Attempt onto the frozen Review Detail DTO."""

    attempt_id = snapshot.attempt_id
    source = github_source_view(snapshot, check_run_id=check_run_id)
    authority = github_authority_for_attempt(attempt_id=attempt_id, change_state=change_state)
    publication = publication_status or (
        PublicationStatus.QUEUED if check_run_id is not None else PublicationStatus.NOT_APPLICABLE
    )
    display_name = snapshot.change_request.repository
    source_payload = source.model_dump()
    if result_json:
        report = load_review_report_from_cli_result(result_json)
        run_status = RunStatus.COMPLETED.value
        gate_state = project_gate_state(report.gate_state).value
        bypass_by_fingerprint = {record.finding_fingerprint: record for record in bypasses}
        active_bypassed = {
            record.finding_fingerprint
            for record in bypasses
            if record.status is BypassStatus.ACTIVE
        }
        if not bypasses:
            run_bypass_state = BypassState.NONE
        elif active_bypassed:
            run_bypass_state = BypassState.ACTIVE
        else:
            run_bypass_state = BypassState.INVALIDATED
        standing_gate = (
            None
            if change_state.standing_gate_state is None
            else change_state.standing_gate_state.value
        )
        surface = SurfaceProjection(
            source=source,
            run_status=RunStatus.COMPLETED,
            authority=authority,
            publication_status=publication,
            bypass_state=run_bypass_state,
            session_insight_connected=session_insight_state == "connected",
            github_actor_authenticated=actor_authenticated and bypass_capability == "available",
            bypass_preconditions_met=bypass_preconditions_met,
        )
        actions = project_available_actions(
            gate_state=project_gate_state(report.gate_state),
            surface=surface,
        )
        if blocking_policy is not None and review_policy_trusted:
            # The frozen Review Policy from the execution snapshot decides
            # what blocks — never a hardcoded severity/band table (P3 §5.1.5).
            blocking = [
                finding.fingerprint
                for finding in report.findings
                if finding_blocks_under_policy(finding, blocking_policy)
            ]
        else:
            # Untrusted / missing Policy: fail closed. Do not invent blockers
            # from a hardcoded Critical/Major table; Bypass stays disabled.
            blocking = []
        identity_unavailable = (
            None
            if report.review_identity is not None
            else "Review identity unavailable — merge candidate was not constructed."
        )
        dimensions = [
            {
                "dimension_id": outcome.dimension_id,
                "status": outcome.status.value,
                "elapsed_ms": None,
                "finding_count": sum(
                    1 for finding in report.findings if finding.dimension_id == outcome.dimension_id
                ),
                "blocking_finding_count": sum(
                    1
                    for finding in report.findings
                    if finding.dimension_id == outcome.dimension_id
                    and finding.fingerprint in blocking
                ),
            }
            for outcome in report.dimension_outcomes
        ]
        failed = next(
            (
                outcome
                for outcome in report.execution.outcomes
                if outcome.status is StageStatus.FAILED
            ),
            None,
        )
        summary = _summary_dto(
            attempt_id=attempt_id,
            display_name=display_name,
            source=source_payload,
            run_status=run_status,
            gate_state=gate_state,
            created_at=created_at,
            finding_count=len(report.findings),
            highest_severity=_highest_severity(report),
            cost_usd=_cost_number(None),
            cost_unknown=True,
            provider=report.compute_policy_disclosure.provider,
            model=report.compute_policy_disclosure.model,
            completed_at=created_at.isoformat(),
            authority=authority.value,
            publication_status=publication.value,
        )
        return {
            "attempt_id": attempt_id,
            "run_status": run_status,
            "gate_state": gate_state,
            "authority": authority.value,
            "publication_status": publication.value,
            "bypass_state": run_bypass_state.value,
            # P3 §8.2 standing projection: the immutable Core gate and the
            # platform standing decision are reported side by side; a remote
            # Check sync lag never disguises either.
            "core_gate_state": report.gate_state.value,
            "standing_gate_state": standing_gate,
            "standing_revision": change_state.standing_revision,
            "check_sync_status": check_sync_status,
            "bypass_capability": bypass_capability,
            "review_policy_trusted": review_policy_trusted,
            "source": source_payload,
            "summary": summary,
            "gate": {
                "gate_state": gate_state,
                "blocking_fingerprints": blocking,
                "remaining_blocking_fingerprints": [
                    fingerprint for fingerprint in blocking if fingerprint not in active_bypassed
                ],
                "summary": report.summary,
                "required_coverage_complete": (
                    report.coverage.required_coverage_complete if report.coverage else False
                ),
            },
            "findings": [
                _finding_dto(
                    finding,
                    blocking=finding.fingerprint in blocking,
                    bypass_record=bypass_by_fingerprint.get(finding.fingerprint),
                )
                for finding in report.findings
            ],
            "coverage": _coverage_from_report(report),
            "dimensions": dimensions,
            "pipeline": _pipeline_from_report(report),
            "failure": None
            if failed is None
            else {
                "stage": failed.stage.value,
                "category": "pipeline",
                "safe_detail": failed.detail or report.error_detail or "stage failed",
            },
            "attempts": [
                {
                    "attempt_id": attempt_id,
                    "authority": authority.value,
                    "gate_state": gate_state,
                    "trigger": "github-pull-request",
                    "provider": report.compute_policy_disclosure.provider,
                    "model": report.compute_policy_disclosure.model,
                    "review_policy_version": report.review_policy_version.semver,
                    "compute_policy_version": report.compute_policy_version.semver,
                    "token_count": None,
                    "cost_usd": None,
                    "cost_unknown": True,
                    "started_at": created_at.isoformat(),
                    "duration_ms": None,
                }
            ],
            "identity": {
                "review_request_key": (
                    f"{report.request_key.source_repository}:"
                    f"{report.request_key.target_ref}:"
                    f"{report.request_key.target_head_oid}:"
                    f"{report.request_key.proposed_head_oid}"
                ),
                "source_repository": report.resolved.source_repository,
                "target_ref": report.resolved.target_ref,
                "target_head_oid": report.resolved.target_head_oid,
                "proposed_source": report.resolved.proposed_source.value,
                "proposed_head_oid": report.resolved.proposed_head_oid,
                "merge_tree_oid": report.merge_tree_oid,
                "review_identity": (
                    None
                    if report.review_identity is None
                    else report.review_identity.candidate.merge_tree_oid
                ),
                "identity_unavailable_reason": identity_unavailable,
            },
            "policies": {
                "review_policy_name": "review-policy",
                "review_policy_version": report.review_policy_version.semver,
                "review_policy_sha256": report.review_policy_version.sha256,
                "compute_policy_name": "compute-policy",
                "compute_policy_version": report.compute_policy_version.semver,
                "compute_policy_sha256": report.compute_policy_version.sha256,
                "data_destination": report.compute_policy_disclosure.data_destination,
                "retention_disclosure": report.compute_policy_disclosure.known_retention,
                "provider_configuration_fingerprint": (
                    report.compute_policy_disclosure.provider_configuration_fingerprint
                ),
            },
            "usage": _usage_from_report(report),
            "provider_health": {
                "profile_name": report.compute_policy_disclosure.provider,
                "status": "not_tested",
                "observed_at": None,
            },
            "available_actions": actions.model_dump(),
            "session_insight_deep_link": session_insight_deep_link,
        }

    job_failed = job_status == "failed"
    gate_state = ViewGateState.ERROR.value if job_failed else ViewGateState.IN_PROGRESS.value
    run_status = RunStatus.FAILED if job_failed else RunStatus.QUEUED
    summary = _summary_dto(
        attempt_id=attempt_id,
        display_name=display_name,
        source=source_payload,
        run_status=run_status.value,
        gate_state=gate_state,
        created_at=created_at,
        authority=authority.value,
        publication_status=publication.value,
    )
    surface = SurfaceProjection(
        source=source,
        run_status=run_status,
        authority=authority,
        publication_status=publication,
        bypass_state=BypassState.NONE,
        session_insight_connected=session_insight_state == "connected",
    )
    actions = project_available_actions(
        gate_state=ViewGateState.IN_PROGRESS,
        surface=surface,
    )
    failure = None
    if job_failed:
        failure = {
            "stage": "worker",
            "category": "retry-exhausted",
            "safe_detail": job_failure_detail
            or "Attempt exhausted its retry budget before producing a terminal result.",
        }
    return {
        "attempt_id": attempt_id,
        "run_status": run_status.value,
        "gate_state": gate_state,
        "authority": authority.value,
        "publication_status": publication.value,
        "bypass_state": BypassState.NONE.value,
        "source": source_payload,
        "summary": summary,
        "gate": {
            "gate_state": gate_state,
            "blocking_fingerprints": [],
            "summary": (
                "Attempt failed after exhausting its retry budget"
                if job_failed
                else "Attempt queued"
            ),
            "required_coverage_complete": False,
        },
        "findings": [],
        "coverage": {
            "required_coverage": "incomplete",
            "reviewed_count": 0,
            "excluded_count": 0,
            "missing_count": 0,
            "files": [],
        },
        "dimensions": [],
        "pipeline": _empty_pipeline(),
        "failure": failure,
        "attempts": [
            {
                "attempt_id": attempt_id,
                "authority": authority.value,
                "gate_state": gate_state,
                "trigger": "github-pull-request",
                "provider": "unknown",
                "model": "unknown",
                "review_policy_version": snapshot.review_policy_semver,
                "compute_policy_version": snapshot.compute_policy_semver,
                "token_count": None,
                "cost_usd": None,
                "cost_unknown": True,
                "started_at": created_at.isoformat(),
                "duration_ms": None,
            }
        ],
        "identity": {
            "review_request_key": (
                f"{snapshot.request_key.source_repository}:"
                f"{snapshot.request_key.target_ref}:"
                f"{snapshot.request_key.target_head_oid}:"
                f"{snapshot.request_key.proposed_head_oid}"
            ),
            "source_repository": snapshot.request_key.source_repository,
            "target_ref": snapshot.request_key.target_ref,
            "target_head_oid": snapshot.request_key.target_head_oid,
            "proposed_source": "github-pull-request",
            "proposed_head_oid": snapshot.request_key.proposed_head_oid,
            "merge_tree_oid": None,
            "review_identity": None,
            "identity_unavailable_reason": (
                "Review identity is assigned after merge construction."
            ),
        },
        "policies": {
            "review_policy_name": "review-policy",
            "review_policy_version": snapshot.review_policy_semver,
            "review_policy_sha256": snapshot.review_policy_sha256,
            "compute_policy_name": "compute-policy",
            "compute_policy_version": snapshot.compute_policy_semver,
            "compute_policy_sha256": snapshot.compute_policy_sha256,
            "data_destination": "unknown",
            "retention_disclosure": "unknown",
            "provider_configuration_fingerprint": None,
        },
        "usage": {
            "estimated_cost_usd": None,
            "actual_cost_usd": None,
            "cost_unknown": True,
            "unknown_cost_record_count": 0,
            "input_tokens": None,
            "output_tokens": None,
            "calls": [],
        },
        "provider_health": {
            "profile_name": "unknown",
            "status": "not_tested",
            "observed_at": None,
        },
        "available_actions": actions.model_dump(),
        "session_insight_deep_link": session_insight_deep_link,
    }


def _highest_severity(report: ReviewReport) -> str | None:
    severities = [finding.severity.value for finding in report.findings]
    if not severities:
        return None
    return max(severities, key=["suggestion", "minor", "major", "critical"].index)


def present_overview(
    aggregate: OverviewAggregate,
    summaries: list[dict[str, Any]],
    *,
    session_insight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attempt_count = aggregate.attempt_count
    gate_pass_rate = aggregate.passed_count / attempt_count if attempt_count else None
    error_rate = aggregate.error_count / attempt_count if attempt_count else None
    active = [row for row in summaries if row["run_status"] in {"queued", "preparing", "running"}]
    attention = [
        row
        for row in summaries
        if row["gate_state"] in {"blocked", "error"} or row["run_status"] == "interrupted"
    ]
    return {
        "attention": attention,
        "active": active,
        "recent": summaries,
        "stats": {
            "attempt_count": aggregate.attempt_count,
            "passed_count": aggregate.passed_count,
            "blocked_count": aggregate.blocked_count,
            "error_count": aggregate.error_count,
            "gate_pass_rate": gate_pass_rate,
            "error_rate": error_rate,
            "average_duration_ms": None,
            "known_cost_usd": float(aggregate.known_cost_usd),
            "unknown_cost_record_count": aggregate.unknown_cost_record_count,
            "known_input_tokens": 0,
            "known_output_tokens": 0,
        },
        "gate_trend": [],
        "finding_severity": [],
        "dimension_health": [],
        "policy_usage": [],
        "provider_health": [],
        "session_insight": session_insight
        or {
            "state": "disconnected",
            "current_attempt_id": None,
            "child_session_count": 0,
            "last_probe_at": None,
        },
    }


def present_repository(row: dict[str, str]) -> dict[str, Any]:
    return {
        "repository_id": row["id"],
        "display_name": row["display_name"],
        "canonical_root": row["canonical_root"],
        "last_gate_state": None,
        "last_reviewed_at": None,
    }


def present_audit_event(event: AuditEvent) -> dict[str, Any]:
    """Read-only audit projection; payloads were sanitized before persistence."""

    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at.isoformat(),
        "installation_id": event.installation_id,
        "repository": event.repository,
        "pull_request_number": event.pull_request_number,
        "attempt_id": event.attempt_id,
        "actor_id": event.actor_id,
        "actor_login": event.actor_login,
        "payload": event.payload,
    }


def present_provider_profile(
    row: dict[str, str | None], *, referenced_by_history: bool = False
) -> dict[str, Any]:
    reference = row.get("credential_reference")
    if not reference:
        credential_state = "missing" if row.get("provider") != "local-cli" else "not_applicable"
    else:
        try:
            name = parse_credential_reference(reference)
            credential_state = "configured" if os.environ.get(name) else "missing"
        except Exception:
            credential_state = "invalid_reference"
    command_raw = row.get("local_cli_command")
    command: list[str] | None = None
    if isinstance(command_raw, str) and command_raw:
        try:
            parsed = json.loads(command_raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            command = [str(argument) for argument in parsed]
    elif isinstance(command_raw, list):
        command = [str(argument) for argument in command_raw]
    return {
        "profile_id": row["id"],
        "name": row["name"],
        "provider": row["provider"],
        "endpoint": row.get("endpoint"),
        "local_cli_adapter": row.get("local_cli_adapter"),
        "local_cli_command": command,
        "adapter_label": row.get("adapter_label"),
        "credential_reference": reference,
        "credential_state": credential_state,
        "last_used_at": None,
        "health": {
            "profile_name": row["name"],
            "status": "not_tested",
            "observed_at": None,
        },
        "referenced_by_history": referenced_by_history,
        "is_default": False,
    }


def present_review_policy(
    row: dict[str, str], policy: ReviewPolicy | None, *, drifted: bool = False
) -> dict[str, Any]:
    return {
        "policy_id": row["id"],
        "drifted": drifted,
        "name": row["path"].rsplit("/", 1)[-1],
        "version": row["version_semver"],
        "sha256": row["version_sha256"],
        "builtin": False,
        "required_dimensions": list(policy.required_dimensions) if policy else [],
        "blocking_severities": (
            [item.value for item in policy.blocking_severities] if policy else []
        ),
        "minimum_blocking_evidence_band": (
            policy.minimum_blocking_evidence_band.value if policy else "supported"
        ),
        "output_language": "en",
        "context_rules": [],
        "mandatory_globs": list(policy.context.mandatory_globs) if policy else [],
        "optional_globs": list(policy.context.optional_globs) if policy else [],
        "excluded_globs": list(policy.context.excluded_globs) if policy else [],
    }


def present_compute_policy(
    row: dict[str, str],
    policy: ComputePolicy | None,
    *,
    provider_profile_name: str | None = None,
    drifted: bool = False,
) -> dict[str, Any]:
    return {
        "policy_id": row["id"],
        "drifted": drifted,
        "name": row["path"].rsplit("/", 1)[-1],
        "version": row["version_semver"],
        "sha256": row["version_sha256"],
        "provider_profile_id": row.get("provider_profile_id") or "",
        "provider_profile_name": provider_profile_name
        or (policy.provider if policy is not None else ""),
        "provider": policy.provider if policy is not None else "",
        "model": policy.model if policy is not None else "",
        "max_output_tokens_per_call": (
            policy.max_output_tokens_per_call if policy is not None else 0
        ),
        "budget_usd": float(policy.max_budget_usd) if policy and policy.max_budget_usd else None,
        "pricing_source": "compute-policy",
        "start_with_uncertain_pricing": (
            policy.allow_start_under_uncertain_price if policy is not None else False
        ),
        "data_destination": policy.data_destination if policy is not None else "",
        "known_retention": policy.known_retention if policy is not None else "",
    }


async def repository_display_name(store: SqliteReviewRunStore, request: dict[str, Any]) -> str:
    repository_id = str(request.get("repository_id") or "")
    if repository_id:
        row = await store.get_repository(repository_id)
        if row is not None:
            return row["display_name"]
    return repository_id or "repository"
