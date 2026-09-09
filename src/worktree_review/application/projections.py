"""Coverage and Usage projections that never guess missing fields."""

from __future__ import annotations

from worktree_review.core.provider import UsageRecord
from worktree_review.core.report import CoverageRecord, ReviewReport

NOT_REPORTED_REASON = "Reason not reported by this result schema"


def project_coverage_files(coverage: CoverageRecord | None) -> list[dict[str, str | None]]:
    if coverage is None:
        return []
    files: list[dict[str, str | None]] = []
    for path in coverage.reviewed:
        files.append({"path": path, "category": "reviewed", "reason": None, "rule": None})
    for path in coverage.mandatory_missing:
        files.append(
            {
                "path": path,
                "category": "mandatory-missing",
                "reason": NOT_REPORTED_REASON,
                "rule": "mandatory-glob",
            }
        )
    for path in coverage.optional_missing:
        files.append(
            {
                "path": path,
                "category": "optional-missing",
                "reason": NOT_REPORTED_REASON,
                "rule": "optional-glob",
            }
        )
    for path in coverage.excluded:
        files.append(
            {
                "path": path,
                "category": "excluded",
                "reason": NOT_REPORTED_REASON,
                "rule": "excluded-glob",
            }
        )
    for path in coverage.unreviewable:
        files.append(
            {
                "path": path,
                "category": "unreviewable",
                "reason": NOT_REPORTED_REASON,
                "rule": None,
            }
        )
    return files


def project_coverage(coverage: CoverageRecord | None) -> dict[str, object]:
    files = project_coverage_files(coverage)
    if coverage is None:
        return {
            "required_coverage": "incomplete",
            "reviewed_count": 0,
            "excluded_count": 0,
            "missing_count": 0,
            "files": files,
        }
    return {
        "required_coverage": "complete" if coverage.required_coverage_complete else "incomplete",
        "reviewed_count": len(coverage.reviewed),
        "excluded_count": len(coverage.excluded),
        "missing_count": len(coverage.mandatory_missing) + len(coverage.optional_missing),
        "files": files,
    }


def project_usage_calls(report: ReviewReport) -> list[dict[str, object | None]]:
    calls: list[dict[str, object | None]] = []
    for ordinal, record in enumerate(report.usage, start=1):
        if not isinstance(record, UsageRecord):
            continue
        cost_unknown = record.cost_usd is None
        calls.append(
            {
                "ordinal": ordinal,
                "dimension_id": None,
                "elapsed_ms": None,
                "provider": record.provider,
                "model": record.model,
                "usage_kind": record.kind.value,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "cost_usd": None if record.cost_usd is None else float(record.cost_usd),
                "cost_unknown": cost_unknown,
                "dimension_id_status": "not-reported",
                "elapsed_status": "not-reported",
            }
        )
    return calls


def project_usage(report: ReviewReport) -> dict[str, object]:
    calls = project_usage_calls(report)
    unknown = sum(1 for call in calls if call["cost_unknown"] is True)
    input_tokens = sum(
        int(call["input_tokens"]) for call in calls if isinstance(call["input_tokens"], int)
    )
    output_tokens = sum(
        int(call["output_tokens"]) for call in calls if isinstance(call["output_tokens"], int)
    )
    actual_values = [call["cost_usd"] for call in calls if isinstance(call["cost_usd"], float)]
    return {
        "estimated_cost_usd": None,
        "actual_cost_usd": sum(actual_values) if actual_values else None,
        "cost_unknown": unknown > 0 or not actual_values,
        "unknown_cost_record_count": unknown,
        "input_tokens": input_tokens if calls else None,
        "output_tokens": output_tokens if calls else None,
        "calls": [
            {key: value for key, value in call.items() if not key.endswith("_status")}
            for call in calls
        ],
    }
