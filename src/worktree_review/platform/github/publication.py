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
    web_review_detail_url,
)
from worktree_review.platform.github.errors import GitHubApiError
from worktree_review.platform.github.persistence import GitHubReviewStore
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
        public_base_url: str | None = None,
    ) -> None:
        self._state = state
        self._github_store = github_store
        self._checks = checks
        self._details_url = details_url
        self._public_base_url = public_base_url

    def _details_url_for(self, attempt_id: str) -> str | None:
        if self._public_base_url:
            return web_review_detail_url(
                public_base_url=self._public_base_url, attempt_id=attempt_id
            )
        return self._details_url

    async def publish_terminal(self, *, attempt_id: str, report: ReviewReport) -> PublishResult:
        check_run_id = await self._github_store.get_check_run_id(attempt_id)
        if check_run_id is None:
            raise GitHubApiError(f"attempt {attempt_id} has no queued check_run_id")
        payload = build_check_run_payload(
            report,
            annotations=limited_annotations(report),
            details_url=self._details_url_for(attempt_id),
        )
        await self._github_store.enqueue_publication(
            PublicationIntent(
                attempt_id=attempt_id,
                check_run_id=check_run_id,
                intent="terminal-check",
                payload=payload.as_github_payload(),
            )
        )
        # The first delivery counts against the bounded retry budget too.
        await self._github_store.claim_publication(attempt_id, respect_backoff=False)
        try:
            publication_decision = await self._state.publish_if_authoritative(
                attempt_id=attempt_id,
                request_key=report.request_key,
                review_identity=report.review_identity,
                gate_state=report.gate_state,
            )
            return await self._deliver(attempt_id, report, publication_decision)
        except GitHubApiError:
            raise
        except Exception as exc:
            # Same rule as retry_outbox: a claimed intent must never squat
            # IN_PROGRESS — release it into the bounded backoff immediately.
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.FAILED, error=str(exc)[:512]
            )
            raise

    async def retry_outbox(self, attempt_id: str, report: ReviewReport) -> PublishResult | None:
        """Recover one pending publication.

        Returns None when there is nothing to do right now (backoff not
        elapsed, retry budget exhausted, or already in flight). Re-runs the
        authoritative CAS before every remote delivery.
        """
        intent = await self._github_store.claim_publication(attempt_id)
        if intent is None:
            status = await self._github_store.publication_status(attempt_id)
            if status is PublicationStatus.PUBLISHED:
                return PublishResult(
                    disposition=PublishDisposition.PUBLISHED,
                    attempt_id=attempt_id,
                    gate_state=report.gate_state,
                    detail="authoritative gate decision was already published",
                )
            if status in (PublicationStatus.QUEUED, PublicationStatus.FAILED):
                # Backoff not elapsed, retry budget exhausted, or another
                # worker holds the claim lease — nothing to do this pass.
                return None
            # Crash window: the result was saved but no intent was ever
            # enqueued. Enqueue now, then run the normal CAS + delivery.
            check_run_id = await self._github_store.get_check_run_id(attempt_id)
            if check_run_id is None:
                await self._github_store.mark_publication(
                    attempt_id,
                    status=PublicationStatus.FAILED,
                    error="missing check_run_id; cannot publish",
                )
                return None
            payload = build_check_run_payload(
                report,
                annotations=limited_annotations(report),
                details_url=self._details_url_for(attempt_id),
            )
            await self._github_store.enqueue_publication(
                PublicationIntent(
                    attempt_id=attempt_id,
                    check_run_id=check_run_id,
                    intent="terminal-check",
                    payload=payload.as_github_payload(),
                )
            )
            if await self._github_store.claim_publication(attempt_id) is None:
                return None
        try:
            publication_decision = await self._state.publish_if_authoritative(
                attempt_id=attempt_id,
                request_key=report.request_key,
                review_identity=report.review_identity,
                gate_state=report.gate_state,
            )
            return await self._deliver(attempt_id, report, publication_decision)
        except GitHubApiError:
            raise
        except Exception as exc:
            # A claimed intent must never squat IN_PROGRESS: release it into
            # the bounded backoff so a later pass (or the terminal FAILED
            # state) owns it.
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.FAILED, error=str(exc)[:512]
            )
            raise

    async def _deliver(
        self, attempt_id: str, report: ReviewReport, publication_decision: PublishResult
    ) -> PublishResult:
        check_run_id = await self._github_store.get_check_run_id(attempt_id)
        if check_run_id is None:
            await self._github_store.mark_publication(
                attempt_id, status=PublicationStatus.FAILED, error="missing check_run_id"
            )
            return publication_decision
        payload = build_check_run_payload(
            report,
            annotations=limited_annotations(report),
            details_url=self._details_url_for(attempt_id),
        )
        if publication_decision.disposition is not PublishDisposition.PUBLISHED:
            # This Attempt's own Check may complete as audit-only. Never create a
            # new Check, and never PATCH the successor Attempt's check_run_id.
            try:
                await self._checks.update_check_run(
                    repository=report.resolved.source_repository,
                    check_run_id=check_run_id,
                    payload=payload,
                )
            except GitHubApiError:
                pass
            # Terminal, not FAILED: superseded publications never enter the
            # retry backoff — re-delivering them is never useful.
            await self._github_store.mark_publication(
                attempt_id,
                status=PublicationStatus.SUPERSEDED,
                error="superseded before publication",
            )
            return publication_decision
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
            return publication_decision
        await self._github_store.mark_publication(attempt_id, status=PublicationStatus.PUBLISHED)
        return publication_decision
