"""Human-readable terminal report for a surface-neutral ReviewReport."""

from mergegate.core.report import ReviewReport


def render_text_report(report: ReviewReport) -> str:
    lines = [
        "MergeGate review",
        f"Gate: {report.gate_state.value}",
        f"Repository: {report.resolved.source_repository}",
        f"Target ref: {report.resolved.target_ref}",
        f"Target head: {report.resolved.target_head_oid}",
        f"Proposed ref: {report.resolved.proposed_ref}",
        f"Proposed head: {report.resolved.proposed_head_oid}",
        f"Merge tree: {report.merge_tree_oid or '(not constructed)'}",
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
    lines.append(f"Summary: {report.summary}")
    if report.error_detail:
        lines.append(f"Error: {report.error_detail}")
    return "\n".join(lines) + "\n"
