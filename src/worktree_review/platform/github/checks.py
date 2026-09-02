"""Deterministic GitHub Checks payloads, including attempt-id fingerprints (D9, D13).

This module only maps a surface-neutral :class:`ReviewReport` to GitHub's
transport shape. It does not decide the gate state, and it does not infer
inline annotations from provider output. A future HTTP publisher can send the
first payload and then append the batches returned by
``build_check_run_payload_batches``.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from worktree_review.core.findings import EvidenceSpan, Finding, Severity
from worktree_review.core.report import (
    TERMINAL_GATE_STATES,
    GateState,
    ReviewReport,
)

CHECK_RUN_NAME = "Worktree Review"
CHECK_RUN_ANNOTATION_BATCH_SIZE = 50
ATTEMPT_FINGERPRINT_LENGTH = 12


class CheckRunStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CheckRunConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class AnnotationLevel(StrEnum):
    NOTICE = "notice"
    WARNING = "warning"
    FAILURE = "failure"


class CheckRunAnnotation(BaseModel):
    """One annotation already proven commentable by the GitHub mapping layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    annotation_level: AnnotationLevel
    message: str = Field(min_length=1)
    title: str = Field(min_length=1)

    @model_validator(mode="after")
    def _line_range_is_ordered(self) -> CheckRunAnnotation:
        if self.end_line < self.start_line:
            raise ValueError("check-run annotation end_line must not precede start_line")
        return self


class CheckRunOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    text: str = Field(min_length=1)
    annotations: tuple[CheckRunAnnotation, ...] = ()


class CheckRunPayload(BaseModel):
    """One create/update payload for GitHub's Checks API."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = CHECK_RUN_NAME
    head_sha: str = Field(min_length=1)
    status: CheckRunStatus
    conclusion: CheckRunConclusion | None = None
    details_url: str | None = None
    external_id: str = Field(min_length=1)
    output: CheckRunOutput

    def as_github_payload(self) -> dict[str, object]:
        """Serialize using GitHub field names while omitting inapplicable nulls."""

        return self.model_dump(mode="json", exclude_none=True)


class CheckRunTransport(Protocol):
    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        """Create a check run and return its GitHub identifier."""
        ...

    async def update_check_run(
        self,
        *,
        repository: str,
        check_run_id: int,
        payload: CheckRunPayload,
    ) -> None:
        """Update one existing check run with another payload batch."""
        ...


def attempt_fingerprint(attempt_id: str) -> str:
    """Return the short, descriptive Attempt fingerprint required by D9."""

    if not attempt_id:
        raise ValueError("Attempt ID must not be empty")
    return sha256(attempt_id.encode("utf-8")).hexdigest()[:ATTEMPT_FINGERPRINT_LENGTH]


def annotation_level_for_severity(severity: Severity) -> AnnotationLevel:
    """Map core severity to GitHub's presentation-only annotation level."""

    if severity in (Severity.CRITICAL, Severity.MAJOR):
        return AnnotationLevel.FAILURE
    if severity is Severity.MINOR:
        return AnnotationLevel.WARNING
    return AnnotationLevel.NOTICE


def check_run_annotation_batches(
    annotations: Iterable[CheckRunAnnotation],
) -> tuple[tuple[CheckRunAnnotation, ...], ...]:
    """Split annotations into GitHub's maximum 50-annotation request batches."""

    materialized_annotations = tuple(annotations)
    return tuple(
        tuple(materialized_annotations[batch_start : batch_start + CHECK_RUN_ANNOTATION_BATCH_SIZE])
        for batch_start in range(
            0,
            len(materialized_annotations),
            CHECK_RUN_ANNOTATION_BATCH_SIZE,
        )
    ) or ((),)


def build_check_run_payload(
    report: ReviewReport,
    *,
    annotations: tuple[CheckRunAnnotation, ...] = (),
    details_url: str | None = None,
) -> CheckRunPayload:
    """Build one deterministic Checks payload for a report and annotation batch."""

    if len(annotations) > CHECK_RUN_ANNOTATION_BATCH_SIZE:
        raise ValueError(
            "a GitHub check-run payload cannot contain more than "
            f"{CHECK_RUN_ANNOTATION_BATCH_SIZE} annotations"
        )
    fingerprint = attempt_fingerprint(report.attempt_id)
    return CheckRunPayload(
        head_sha=report.resolved.proposed_head_oid,
        status=_status_for_gate(report.gate_state),
        conclusion=_conclusion_for_gate(report.gate_state),
        details_url=details_url,
        external_id=f"worktree-review:{report.attempt_id}",
        output=CheckRunOutput(
            title=f"{CHECK_RUN_NAME}: {report.gate_state.value}",
            summary=_render_summary(report, fingerprint),
            text=_render_detail(report, fingerprint),
            annotations=annotations,
        ),
    )


def build_check_run_payload_batches(
    report: ReviewReport,
    *,
    annotations: Iterable[CheckRunAnnotation] = (),
    details_url: str | None = None,
) -> tuple[CheckRunPayload, ...]:
    """Build the create payload plus deterministic annotation update payloads."""

    return tuple(
        build_check_run_payload(
            report,
            annotations=annotation_batch,
            details_url=details_url,
        )
        for annotation_batch in check_run_annotation_batches(annotations)
    )


def _status_for_gate(gate_state: GateState) -> CheckRunStatus:
    if gate_state is GateState.AWAITING_REVIEW:
        return CheckRunStatus.QUEUED
    if gate_state is GateState.IN_PROGRESS:
        return CheckRunStatus.IN_PROGRESS
    return CheckRunStatus.COMPLETED


def _conclusion_for_gate(gate_state: GateState) -> CheckRunConclusion | None:
    if gate_state not in TERMINAL_GATE_STATES:
        return None
    if gate_state in (GateState.PASSED, GateState.PASSED_WITH_BYPASS):
        return CheckRunConclusion.SUCCESS
    return CheckRunConclusion.FAILURE


def _render_summary(report: ReviewReport, fingerprint: str) -> str:
    lines = [
        f"**Gate:** `{_escape_markdown(report.gate_state.value)}`",
        f"**Attempt fingerprint:** `{fingerprint}`",
        f"**Proposed head:** `{_escape_markdown(report.resolved.proposed_head_oid)}`",
    ]
    if report.merge_tree_oid is not None:
        lines.append(f"**Merge tree:** `{_escape_markdown(report.merge_tree_oid)}`")
    if report.review_identity is None:
        lines.append("**Review Identity:** unavailable")
    return "\n\n".join(lines)


def _render_detail(report: ReviewReport, fingerprint: str) -> str:
    sections = [
        _escape_markdown(report.summary),
        f"Attempt fingerprint: `{fingerprint}`",
        _render_provenance(report),
        _render_coverage(report),
        _render_findings("Findings", report.findings),
    ]
    if report.draft_findings:
        sections.append(
            _render_findings(
                "Draft findings (not gate evidence)",
                report.draft_findings,
            )
        )
    if report.error_detail:
        sections.append(f"**Error:** {_escape_markdown(report.error_detail)}")
    return "\n\n".join(section for section in sections if section)


def _render_provenance(report: ReviewReport) -> str:
    request_key = report.request_key
    lines = [
        "**Review Request Key:** "
        f"`{_escape_markdown(request_key.source_repository)}` "
        f"target `{_escape_markdown(request_key.target_ref)}` "
        f"`{_escape_markdown(request_key.target_head_oid)}` → "
        f"`{_escape_markdown(request_key.proposed_head_oid)}`",
        "**Review Policy:** "
        f"{_escape_markdown(report.review_policy_version.semver)} "
        f"`{_escape_markdown(report.review_policy_version.sha256)}`",
        "**Compute Policy:** "
        f"{_escape_markdown(report.compute_policy_version.semver)} "
        f"`{_escape_markdown(report.compute_policy_version.sha256)}`",
    ]
    if report.review_identity is not None:
        lines.append(
            "**Review Identity merge tree:** "
            f"`{_escape_markdown(report.review_identity.candidate.merge_tree_oid)}`"
        )
    else:
        lines.append("**Review Identity:** unavailable")
    return "\n".join(lines)


def _render_coverage(report: ReviewReport) -> str:
    if report.coverage is None:
        return "**Coverage:** unavailable"
    coverage_state = "complete" if report.coverage.required_coverage_complete else "incomplete"
    lines = [f"**Coverage:** {coverage_state}"]
    if report.coverage.mandatory_missing:
        lines.append(
            "Mandatory missing: "
            + ", ".join(_escape_markdown(item) for item in report.coverage.mandatory_missing)
        )
    if report.coverage.optional_missing:
        lines.append(
            "Optional missing: "
            + ", ".join(_escape_markdown(item) for item in report.coverage.optional_missing)
        )
    if report.coverage.unreviewable:
        lines.append(
            "Unreviewable: "
            + ", ".join(_escape_markdown(item) for item in report.coverage.unreviewable)
        )
    return "\n".join(lines)


def _render_findings(title: str, findings: tuple[Finding, ...]) -> str:
    if not findings:
        return f"### {title}\nNo findings."
    rendered_findings: list[str] = [f"### {title}"]
    for finding in findings:
        rendered_findings.append(
            "- "
            f"`{finding.fingerprint[:ATTEMPT_FINGERPRINT_LENGTH]}` "
            f"**{finding.severity.value}** / "
            f"`{finding.evidence_band.value}`: "
            f"{_escape_markdown(finding.problem_statement)}"
        )
        for span in finding.evidence_spans:
            rendered_findings.append(f"  - {_render_span(span)}")
    return "\n".join(rendered_findings)


def _render_span(span: EvidenceSpan) -> str:
    location = f"{span.path}:{span.start_line}-{span.end_line}"
    quote = _escape_markdown(span.quoted_text.replace("\n", "\\n"))
    return f"evidence `{_escape_markdown(location)}` ({span.source.value}): `{quote}`"


def _escape_markdown(value: str) -> str:
    return html.escape(value.replace("`", "\\`"), quote=False)


async def publish_check_run(
    report: ReviewReport,
    *,
    transport: CheckRunTransport,
    annotations: Iterable[CheckRunAnnotation] = (),
    details_url: str | None = None,
) -> int:
    """Create one check run and append any remaining annotation batches."""

    payloads = build_check_run_payload_batches(
        report,
        annotations=annotations,
        details_url=details_url,
    )
    repository = report.request_key.source_repository
    check_run_id = await transport.create_check_run(
        repository=repository,
        payload=payloads[0],
    )
    for payload in payloads[1:]:
        await transport.update_check_run(
            repository=repository,
            check_run_id=check_run_id,
            payload=payload,
        )
    return check_run_id
