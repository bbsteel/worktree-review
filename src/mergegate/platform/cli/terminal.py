"""Human-readable terminal report for a surface-neutral ReviewReport."""

from mergegate.core.report import ReviewReport


def render_text_report(report: ReviewReport) -> str:
    lines = [
        "MergeGate review",
        f"Gate: {report.gate_state.value}",
        f"Attempt: {report.attempt_id}",
        f"Repository: {report.resolved.source_repository}",
        f"Target ref: {report.resolved.target_ref}",
        f"Target head: {report.resolved.target_head_oid}",
        f"Proposed ref: {report.resolved.proposed_ref}",
        f"Proposed head: {report.resolved.proposed_head_oid}",
        (
            f"Merge tree: {report.merge_tree_oid or '(not constructed)'}"
            if report.review_identity is None
            else f"Merge tree: {report.review_identity.candidate.merge_tree_oid}"
        ),
        (
            "Review policy: "
            f"{report.review_policy_version.semver} "
            f"{report.review_policy_version.sha256}"
        ),
        (
            "Compute policy: "
            f"{report.compute_policy_version.semver} "
            f"{report.compute_policy_version.sha256}"
        ),
        "Stages:",
    ]
    for outcome in report.execution.outcomes:
        suffix = f" ({outcome.detail})" if outcome.detail else ""
        lines.append(f"  {outcome.stage.value}: {outcome.status.value}{suffix}")
    if report.coverage is not None:
        lines.append(
            "Coverage: "
            + ("complete" if report.coverage.required_coverage_complete else "incomplete")
        )
        if report.coverage.reviewed:
            lines.append("  reviewed: " + ", ".join(report.coverage.reviewed))
        if report.coverage.excluded:
            lines.append("  excluded: " + ", ".join(report.coverage.excluded))
        if report.coverage.unreviewable:
            lines.append("  unreviewable: " + ", ".join(report.coverage.unreviewable))
        if report.coverage.mandatory_missing:
            lines.append("  mandatory missing: " + ", ".join(report.coverage.mandatory_missing))
        if report.coverage.optional_missing:
            lines.append("  optional missing: " + ", ".join(report.coverage.optional_missing))
    if report.draft_findings:
        lines.append(
            f"Unverified draft findings: {len(report.draft_findings)} "
            "(not evidence; verification did not complete)"
        )
    if report.usage:
        lines.append("Usage:")
        for record in report.usage:
            cost = "unknown" if record.cost_usd is None else f"${record.cost_usd}"
            lines.append(
                f"  {record.kind.value} {record.provider}/{record.model} "
                f"in={record.input_tokens} out={record.output_tokens} cost={cost}"
            )
    lines.append(f"Summary: {report.summary}")
    if report.error_detail:
        lines.append(f"Error: {report.error_detail}")
    return "\n".join(lines) + "\n"
