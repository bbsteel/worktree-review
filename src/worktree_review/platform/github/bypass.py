"""Authorized per-finding GitHub bypass coordination (PRD §16; TECH-DESIGN D9).

A bypass accepts the risk of one blocking Finding on the current standing
authoritative Attempt. It never means the Finding was resolved, it always
requires a live authorized GitHub actor and a safe non-empty reason, and it
binds to the Review Identity and the frozen Review Policy that produced the
standing decision. An Error gate can never become Passed with bypass through
this path, because an incomplete review means unknown risk.

The durable state transition (bypass + audit + standing revision + Check sync
intent in one transaction) lives in ``AuthoritativeAttemptStore``; this module
validates the request against the frozen execution inputs before delegating.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.application.lifecycle import PublicationStatus
from worktree_review.application.review_events import scrub_secret_content
from worktree_review.core.findings import Finding
from worktree_review.core.gate import finding_blocks_under_policy
from worktree_review.core.policy import ReviewPolicy
from worktree_review.core.report import GateState, ReviewReport, StageName, StageStatus
from worktree_review.platform.cli.result import load_review_report_from_cli_result
from worktree_review.platform.github.frozen_policy import (
    FrozenReviewPolicyError,
    resolve_frozen_review_policy,
)
from worktree_review.platform.github.persistence import GitHubReviewStore
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.server.state import (
    AuthoritativeAttemptStore,
    BypassApplyResult,
    GitHubChangeRequestLocator,
    StateConflictError,
)

MAX_REASON_CHARS = 2000
MAX_REASON_UTF8_BYTES = 8 * 1024
MAX_REASON_LINE_CHARS = 500


class BypassAuthorizationError(RuntimeError):
    """The live GitHub actor is not authorized to accept finding risk."""


class BypassAuthorizationUnavailableError(RuntimeError):
    """The external authorization signal is undecidable; nothing was written."""


class BypassStorageUnavailableError(RuntimeError):
    """The authoritative store failed; the transaction rolled back atomically."""


class BypassRejectionError(RuntimeError):
    """The bypass request violates domain rules; ``code`` is stable for API mapping."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class BypassRequest(BaseModel):
    """One per-finding risk-acceptance request from an authorized GitHub actor.

    The actor arrives here only after the deployment authentication layer has
    verified the GitHub identity for this very request; ``actor_id`` is the
    stable numeric user ID, ``actor_login`` the display name.
    """

    model_config = ConfigDict(frozen=True)

    attempt_id: str = Field(min_length=1)
    finding_fingerprint: str = Field(min_length=1)
    actor_id: int | None = Field(default=None, gt=0)
    actor_login: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class BypassAccepted(BaseModel):
    """The persisted bypass and the standing gate after it was applied."""

    model_config = ConfigDict(frozen=True)

    result: BypassApplyResult

    @property
    def replayed(self) -> bool:
        return self.result.replayed


class BypassAuthorizer(Protocol):
    async def may_bypass(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        actor_login: str,
    ) -> bool:
        """Resolve the current repository role from GitHub, never request text."""
        ...


def validate_bypass_reason(reason: str) -> str:
    """Return the normalized reason or raise ``bypass_reason_invalid`` (422).

    Reasons are bounded plain text: no code fences, no single very long line,
    and nothing that the secret scrubber would alter — a recognized token or a
    live credential value means the user must rewrite, never silent storage.
    """

    stripped = reason.strip()
    if not stripped:
        raise BypassRejectionError("bypass_reason_invalid", "a non-empty reason is required")
    if len(stripped) > MAX_REASON_CHARS:
        raise BypassRejectionError("bypass_reason_invalid", "reason exceeds 2000 characters")
    if len(stripped.encode("utf-8")) > MAX_REASON_UTF8_BYTES:
        raise BypassRejectionError("bypass_reason_invalid", "reason exceeds 8 KiB of UTF-8")
    if "```" in stripped:
        raise BypassRejectionError(
            "bypass_reason_invalid", "reason is plain text: code fences are not allowed"
        )
    if any(len(line) > MAX_REASON_LINE_CHARS for line in stripped.splitlines()):
        raise BypassRejectionError(
            "bypass_reason_invalid", "reason lines must not exceed 500 characters"
        )
    if scrub_secret_content(stripped) != stripped:
        raise BypassRejectionError(
            "bypass_reason_invalid",
            "reason contains credential-shaped content; rewrite it without secrets",
        )
    return stripped


def risk_snapshot_for_finding(finding: Finding) -> dict[str, object]:
    """Bind the bypass to the problem, severity, impact, and evidence locations.

    Quoted source text never enters the snapshot: audit must not carry source
    code, only verifiable references to it.
    """

    return {
        "severity": finding.severity.value,
        "evidence_band": finding.evidence_band.value,
        "dimension_id": finding.dimension_id,
        "problem_statement": finding.problem_statement,
        "expected_impact": finding.expected_impact,
        "evidence_spans": [
            {
                "path": span.path,
                "start_line": span.start_line,
                "end_line": span.end_line,
                "source": span.source.value,
                "snapshot_identity": span.snapshot_identity,
                "change_kind": None if span.change_kind is None else span.change_kind.value,
            }
            for span in finding.evidence_spans
        ],
    }


def risk_digest_for_snapshot(risk_snapshot: dict[str, object]) -> str:
    """SHA-256 over the canonical snapshot JSON: "substantively unchanged"
    requires every field to match, never just the fingerprint."""

    canonical = json.dumps(risk_snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_COMPLETE_REVIEW_STAGES = frozenset(
    {
        StageName.DERIVE_IDENTITY,
        StageName.CONSTRUCT_MERGE,
        StageName.GATHER_CONTEXT,
        StageName.RUN_DIMENSIONS,
        StageName.VERIFY_DEDUP,
        StageName.CHECK_COMPLETENESS,
        StageName.EVALUATE_GATE,
    }
)


def report_is_complete_blocked(report: ReviewReport) -> bool:
    """A bypass needs a complete Blocked review: never trust the single
    ``gate_state`` field — required stages, coverage, and identity must all
    be present so the remaining risk is actually known."""

    if report.gate_state is not GateState.BLOCKED:
        return False
    if report.review_identity is None:
        return False
    completed = {
        outcome.stage
        for outcome in report.execution.outcomes
        if outcome.status is StageStatus.COMPLETED
    }
    if not _COMPLETE_REVIEW_STAGES.issubset(completed):
        return False
    if report.coverage is None or not report.coverage.required_coverage_complete:
        return False
    return True


class GitHubBypassCoordinator:
    """Authorize, validate, and transactionally apply one finding bypass."""

    def __init__(
        self,
        *,
        state: AuthoritativeAttemptStore,
        github_store: GitHubReviewStore,
        authorizer: BypassAuthorizer,
        review_policy_path: Path,
    ) -> None:
        self._state = state
        self._github_store = github_store
        self._authorizer = authorizer
        self._review_policy_path = review_policy_path

    async def request_bypass(self, bypass_request: BypassRequest) -> BypassAccepted:
        reason = validate_bypass_reason(bypass_request.reason)
        snapshot = await self._github_store.get_execution_snapshot(bypass_request.attempt_id)
        if snapshot is None:
            raise BypassRejectionError("attempt_not_found", "unknown GitHub attempt")
        change_request = snapshot.change_request

        try:
            authorized = await self._authorizer.may_bypass(
                change_request=change_request,
                actor_login=bypass_request.actor_login,
            )
        except Exception as exc:
            raise BypassAuthorizationUnavailableError(
                "the live repository role could not be determined"
            ) from exc
        if not authorized:
            await self._state.append_audit_event(
                event_type="bypass_denied",
                change_request=change_request,
                attempt_id=bypass_request.attempt_id,
                payload={
                    "finding_fingerprint": bypass_request.finding_fingerprint,
                    "reason": reason,
                },
                actor_id=bypass_request.actor_id,
                actor_login=bypass_request.actor_login,
            )
            raise BypassAuthorizationError(
                f"GitHub actor {bypass_request.actor_login!r} is not authorized to bypass findings"
            )

        # Authority/standing pre-check; the store re-verifies inside the CAS
        # transaction, so a stale read here can only produce a clean 409.
        current_state = await self._state.get_change_request_state(change_request)
        if (
            current_state.authoritative_attempt_id != bypass_request.attempt_id
            or current_state.standing_attempt_id != bypass_request.attempt_id
        ):
            raise BypassRejectionError(
                "bypass_not_standing",
                "bypass requires the current standing authoritative Attempt",
            )
        if current_state.standing_gate_state is GateState.ERROR:
            raise BypassRejectionError(
                "bypass_gate_error",
                "an Error gate cannot be bypassed: the review did not complete "
                "and the remaining risk is unknown",
            )
        # The standing decision must be published to a real GitHub Check: an
        # unpublished Attempt or one without a Check can never reach
        # "Passed with bypass" through this path, and the sync state must never
        # report not_applicable for a GitHub Attempt (P3 §5.1.2, §6).
        check_run_id = await self._github_store.get_check_run_id(bypass_request.attempt_id)
        publication = await self._github_store.publication_status(bypass_request.attempt_id)
        if check_run_id is None or publication is not PublicationStatus.PUBLISHED:
            raise BypassRejectionError(
                "bypass_not_standing",
                "the standing decision is not published to a GitHub Check",
            )
        # A prior record for this (attempt, fingerprint) short-circuits the
        # gate-state requirement: the gate may legitimately be
        # PASSED_WITH_BYPASS *because of* this very bypass. The store still
        # re-verifies standing and identity transactionally before honoring a
        # replay or raising a conflict (P3 §5.3).
        prior_records = await self._state.list_bypasses(attempt_id=bypass_request.attempt_id)
        prior = next(
            (
                record
                for record in prior_records
                if record.finding_fingerprint == bypass_request.finding_fingerprint
            ),
            None,
        )
        if prior is None and current_state.standing_gate_state is not GateState.BLOCKED:
            raise BypassRejectionError(
                "bypass_not_blocking",
                "only a completed Blocked review has findings that accept risk",
            )

        report = await self._load_terminal_report(bypass_request.attempt_id)
        if not report_is_complete_blocked(report):
            raise BypassRejectionError(
                "bypass_gate_error",
                "the review is incomplete; bypass is unavailable because the "
                "remaining risk is unknown",
            )
        identity = report.review_identity
        assert identity is not None  # guaranteed by report_is_complete_blocked
        review_policy = self._load_frozen_review_policy(snapshot, report)
        if report.request_key != snapshot.request_key:
            raise BypassRejectionError(
                "bypass_not_standing",
                "the candidate moved since the report was produced",
            )

        finding = next(
            (
                candidate
                for candidate in report.findings
                if candidate.fingerprint == bypass_request.finding_fingerprint
            ),
            None,
        )
        if finding is None:
            raise BypassRejectionError(
                "finding_not_found",
                "no finding with this fingerprint exists on the standing Attempt",
            )
        blocking_fingerprints = tuple(
            candidate.fingerprint
            for candidate in report.findings
            if finding_blocks_under_policy(candidate, review_policy)
        )
        if finding.fingerprint not in blocking_fingerprints:
            raise BypassRejectionError(
                "bypass_not_blocking",
                "only findings that block under the frozen Review Policy can be bypassed",
            )

        risk_snapshot = risk_snapshot_for_finding(finding)
        try:
            result = await self._state.apply_finding_bypass(
                change_request=change_request,
                attempt_id=bypass_request.attempt_id,
                finding_fingerprint=bypass_request.finding_fingerprint,
                actor_id=bypass_request.actor_id,
                actor_login=bypass_request.actor_login,
                reason=reason,
                review_identity=identity,
                review_policy_sha256=snapshot.review_policy_sha256,
                blocking_fingerprints=blocking_fingerprints,
                risk_snapshot=risk_snapshot,
                risk_digest=risk_digest_for_snapshot(risk_snapshot),
                check_run_id=check_run_id,
            )
        except StateConflictError as exc:
            raise BypassRejectionError("bypass_conflict", str(exc)) from exc
        except Exception as exc:
            raise BypassStorageUnavailableError(
                "the authoritative store rejected the transaction"
            ) from exc
        return BypassAccepted(result=result)

    async def _load_terminal_report(self, attempt_id: str) -> ReviewReport:
        result_json = await self._github_store.get_review_result(attempt_id)
        if result_json is None:
            raise BypassRejectionError(
                "bypass_not_standing",
                "the Attempt has no terminal review result",
            )
        report = load_review_report_from_cli_result(result_json)
        if report.gate_state is GateState.ERROR:
            raise BypassRejectionError(
                "bypass_gate_error",
                "an Error gate cannot be bypassed: the review did not complete "
                "and the remaining risk is unknown",
            )
        return report

    def _load_frozen_review_policy(
        self, snapshot: AttemptExecutionSnapshot, report: ReviewReport
    ) -> ReviewPolicy:
        """Resolve the Review Policy via the shared frozen-policy trust path."""

        try:
            return resolve_frozen_review_policy(
                snapshot,
                legacy_review_policy_path=self._review_policy_path,
                expected_report_version=report.review_policy_version,
            )
        except FrozenReviewPolicyError as exc:
            raise BypassRejectionError(exc.code, exc.detail) from exc
