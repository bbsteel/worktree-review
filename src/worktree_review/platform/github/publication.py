"""CAS Check publication through an outbox. Remote failures do not rewrite Core Gate."""

from __future__ import annotations

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.core.findings import EvidenceSpan, Finding
from worktree_review.core.report import ReviewReport
from worktree_review.platform.github.checks import (
    CHECK_RUN_ANNOTATION_BATCH_SIZE,
    CheckRunAnnotation,
    CheckRunTransport,
    annotation_level_for_severity,
    build_check_run_payload,
)
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.runtime import GitHubApiError
from worktree_review.platform.github.snapshot import PublicationIntent
from worktree_review.server.state import (
    AuthoritativeAttemptStore,
    PublishDisposition,
    PublishResult,
)


def limited_annotations(report: ReviewReport) -> tuple[CheckRunAnnotation, ...]:
    annotations: list[CheckRunAnnotation] = []
    for finding in report.findings:
        span = _first_span(finding)
        if span is None:
            continue
        annotations.append(
            CheckRunAnnotation(
                path=span.path,
                start_line=span.start_line,
                end_line=span.end_line,
                annotation_level=annotation_level_for_severity(finding.severity),
                message=finding.problem_statement,
                title=finding.fingerprint[:64] or "finding",
            )
        )
        if len(annotations) >= CHECK_RUN_ANNOTATION_BATCH_SIZE:
            break
    return tuple(annotations)


def _first_span(finding: Finding) -> EvidenceSpan | None:
    return finding.evidence_spans[0] if finding.evidence_spans else None


class GitHubCheckPublisher:
    def __init__(
        self,
        *,
        state: AuthoritativeAttemptStore,
        github_store: GitHubReviewStore,
        checks: CheckRunTransport,
        details_url: str | None = None,
    ) -> None:
        self._state = state
        self._github_store = github_store
        self._checks = checks
        self._details_url = details_url

    async def publish_terminal(self, *, attempt_id: str, report: ReviewReport) -> PublishResult:
        check_run_id = await self._github_store.get_check_run_id(attempt_id)
        if check_run_id is None:
            raise GitHubApiError(f"attempt {attempt_id} has no queued check_run_id")
        payload = build_check_run_payload(
            report,
            annotations=limited_annotations(report),
            details_url=self._details_url,
        )
        await self._github_store.enqueue_publication(
            PublicationIntent(
                attempt_id=attempt_id,
                check_run_id=check_run_id,
                intent="terminal-check",
                payload=payload.as_github_payload(),
            )
        )
        cas = await self._state.publish_if_authoritative(
            attempt_id=attempt_id,
            request_key=report.request_key,
            review_identity=report.review_identity,
            gate_state=report.gate_state,
        )
        return await self._deliver(attempt_id, report, cas)

    async def retry_outbox(self, attempt_id: str, report: ReviewReport) -> PublishResult:
        intent = await self._github_store.claim_publication(attempt_id)
        if intent is None:
            raise GitHubApiError(f"no publication intent for {attempt_id}")
        cas = await self._state.publish_if_authoritative(
            attempt_id=attempt_id,
            request_key=report.request_key,
            review_identity=report.review_identity,
            gate_state=report.gate_state,
        )
        return await self._deliver(attempt_id, report, cas)

    async def _deliver(
        self, attempt_id: str, report: ReviewReport, cas: PublishResult
    ) -> PublishResult:
        check_run_id = await self._github_store.get_check_run_id(attempt_id)
        if check_run_id is None:
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.FAILED, error="missing check_run_id"
            )
            return cas
        payload = build_check_run_payload(
            report,
            annotations=limited_annotations(report),
            details_url=self._details_url,
        )
        try:
            await self._checks.update_check_run(
                repository=report.resolved.source_repository,
                check_run_id=check_run_id,
                payload=payload,
            )
        except GitHubApiError as exc:
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.FAILED, error=str(exc)
            )
            return cas
        if cas.disposition is PublishDisposition.PUBLISHED:
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.PUBLISHED
            )
        else:
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.FAILED, error="superseded before publication"
            )
        return cas
