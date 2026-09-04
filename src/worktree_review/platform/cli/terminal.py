"""Human-readable terminal report for a surface-neutral ReviewReport."""

import re

from worktree_review.core.findings import EvidenceSpan, Finding
from worktree_review.core.identity import ProposedSource
from worktree_review.core.report import ReviewReport

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _terminal_safe_text(value: str) -> str:
    """Keep model/repository text from emitting terminal control sequences."""

    without_ansi = _ANSI_ESCAPE_PATTERN.sub(lambda match: repr(match.group(0))[1:-1], value)
    safe_characters: list[str] = []
    for character in without_ansi:
        codepoint = ord(character)
        if character in "\n\t" or 0x20 <= codepoint < 0x7F or codepoint >= 0xA0:
            safe_characters.append(character)
        else:
            safe_characters.append(f"\\x{codepoint:02x}")
    return "".join(safe_characters)


def _append_multiline_field(lines: list[str], label: str, value: str) -> None:
    safe_value = _terminal_safe_text(value)
    value_lines = safe_value.splitlines() or [""]
    lines.append(f"  {label}: {value_lines[0]}")
    lines.extend(f"    {line}" for line in value_lines[1:])


def _safe_path_list(paths: tuple[str, ...]) -> str:
    return ", ".join(_terminal_safe_text(path) for path in paths)


def _render_span(lines: list[str], span: EvidenceSpan) -> None:
    location = f"{_terminal_safe_text(span.path)}:{span.start_line}-{span.end_line}"
    provenance = span.source.value
    if span.snapshot_identity:
        provenance += f" snapshot={_terminal_safe_text(span.snapshot_identity)}"
    if span.change_kind:
        provenance += f" change_kind={span.change_kind.value}"
    lines.append(f"    - {location} [{provenance}]")
    quote_lines = _terminal_safe_text(span.quoted_text).splitlines() or [""]
    lines.append(f"      quote: {quote_lines[0]}")
    lines.extend(f"        {line}" for line in quote_lines[1:])


def _render_finding(
    lines: list[str],
    finding: Finding,
    *,
    finding_number: int,
    finding_label: str = "Finding",
) -> None:
    dimension = finding.dimension_id or "unspecified-dimension"
    bypass_suffix = " [bypassed]" if finding.bypass_applied else ""
    lines.append(
        f"{finding_label} {finding_number}: {finding.severity.value} / "
        f"{finding.evidence_band.value} / {_terminal_safe_text(dimension)}{bypass_suffix}"
    )
    lines.append(f"  fingerprint: {_terminal_safe_text(finding.fingerprint)}")
    if finding.evidence_spans:
        lines.append("  evidence spans:")
        for span in finding.evidence_spans:
            _render_span(lines, span)
    else:
        lines.append("  evidence spans: none")
    _append_multiline_field(lines, "problem", finding.problem_statement)
    _append_multiline_field(lines, "impact", finding.expected_impact)
    if finding.repair_guidance:
        _append_multiline_field(lines, "repair", finding.repair_guidance)


def render_text_report(report: ReviewReport) -> str:
    if report.review_identity is None:
        merge_tree_line = "Merge tree: " + _terminal_safe_text(
            report.merge_tree_oid or "(not constructed)"
        )
        review_identity_line = "Review identity: unavailable"
    else:
        merge_tree_line = "Merge tree: " + _terminal_safe_text(
            report.review_identity.candidate.merge_tree_oid
        )
        review_identity_line = (
            "Review identity: "
            "merge_tree="
            f"{_terminal_safe_text(report.review_identity.candidate.merge_tree_oid)} "
            "policy="
            f"{_terminal_safe_text(report.review_identity.review_policy_version.semver)}/"
            f"{_terminal_safe_text(report.review_identity.review_policy_version.sha256)}"
        )
    lines = [
        "Worktree Review",
        f"Gate: {report.gate_state.value}",
        f"Attempt: {_terminal_safe_text(report.attempt_id)}",
        "Request key:",
        f"  source repository: {_terminal_safe_text(report.request_key.source_repository)}",
        f"  target ref: {_terminal_safe_text(report.request_key.target_ref)}",
        f"  target head: {_terminal_safe_text(report.request_key.target_head_oid)}",
        f"  proposed head: {_terminal_safe_text(report.request_key.proposed_head_oid)}",
        f"Repository: {_terminal_safe_text(report.resolved.source_repository)}",
        f"Target ref: {_terminal_safe_text(report.resolved.target_ref)}",
        f"Target head: {_terminal_safe_text(report.resolved.target_head_oid)}",
        f"Proposed ref: {_terminal_safe_text(report.resolved.proposed_ref)}",
        f"Proposed head: {_terminal_safe_text(report.resolved.proposed_head_oid)}",
        merge_tree_line,
        review_identity_line,
        (
            "Review policy: "
            f"{_terminal_safe_text(report.review_policy_version.semver)} "
            f"{_terminal_safe_text(report.review_policy_version.sha256)}"
        ),
        (
            "Compute policy: "
            f"{_terminal_safe_text(report.compute_policy_version.semver)} "
            f"{_terminal_safe_text(report.compute_policy_version.sha256)}"
        ),
        (
            "Provider/model: "
            f"{_terminal_safe_text(report.compute_policy_disclosure.provider)}/"
            f"{_terminal_safe_text(report.compute_policy_disclosure.model)}"
        ),
        "Data destination: "
        + _terminal_safe_text(report.compute_policy_disclosure.data_destination),
        "Known retention: " + _terminal_safe_text(report.compute_policy_disclosure.known_retention),
        "Stages:",
    ]
    if report.resolved.proposed_source is ProposedSource.CURRENT_WORKTREE_SNAPSHOT:
        lines.insert(8, "Proposed source: current worktree snapshot")
    for stage_outcome in report.execution.outcomes:
        suffix = f" ({_terminal_safe_text(stage_outcome.detail)})" if stage_outcome.detail else ""
        lines.append(f"  {stage_outcome.stage.value}: {stage_outcome.status.value}{suffix}")
    lines.append("Dimensions:")
    if not report.dimension_outcomes:
        lines.append("  none recorded")
    else:
        for dimension_outcome in report.dimension_outcomes:
            suffix = (
                f" ({_terminal_safe_text(dimension_outcome.detail)})"
                if dimension_outcome.detail
                else ""
            )
            lines.append(
                f"  {_terminal_safe_text(dimension_outcome.dimension_id)}: "
                f"{dimension_outcome.status.value}{suffix}"
            )
    if report.coverage is not None:
        lines.append(
            "Coverage: "
            + ("complete" if report.coverage.required_coverage_complete else "incomplete")
        )
        if report.coverage.reviewed:
            lines.append("  reviewed: " + _safe_path_list(report.coverage.reviewed))
        if report.coverage.excluded:
            lines.append("  excluded: " + _safe_path_list(report.coverage.excluded))
        if report.coverage.unreviewable:
            lines.append("  unreviewable: " + _safe_path_list(report.coverage.unreviewable))
        if report.coverage.mandatory_missing:
            lines.append(
                "  mandatory missing: " + _safe_path_list(report.coverage.mandatory_missing)
            )
        if report.coverage.optional_missing:
            lines.append("  optional missing: " + _safe_path_list(report.coverage.optional_missing))
    lines.append(f"Findings: {len(report.findings)}")
    if not report.findings:
        lines.append("  none")
    else:
        for finding_number, finding in enumerate(report.findings, start=1):
            _render_finding(lines, finding, finding_number=finding_number)
    if report.draft_findings:
        lines.append(
            f"Unverified draft findings: {len(report.draft_findings)} "
            "(not evidence; verification did not complete)"
        )
        for finding_number, finding in enumerate(report.draft_findings, start=1):
            _render_finding(
                lines,
                finding,
                finding_number=finding_number,
                finding_label="Draft finding",
            )
    if report.usage:
        lines.append("Usage:")
        for record in report.usage:
            cost = "unknown" if record.cost_usd is None else f"${record.cost_usd}"
            lines.append(
                f"  {record.kind.value} {_terminal_safe_text(record.provider)}/"
                f"{_terminal_safe_text(record.model)} "
                f"in={record.input_tokens} out={record.output_tokens} cost={cost}"
            )
    lines.append(f"Summary: {_terminal_safe_text(report.summary)}")
    if report.error_detail:
        lines.append(f"Error: {_terminal_safe_text(report.error_detail)}")
    return "\n".join(lines) + "\n"
