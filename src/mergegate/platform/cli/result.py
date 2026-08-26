"""Machine-readable CLI result ``mergegate.cli.result/v1`` (PRD §19; D10)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mergegate.core.report import ReviewReport
from mergegate.schemas import CLI_RESULT_SCHEMA_ID, load_schema


class PolicyVersionPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    semver: str
    sha256: str


class StageOutcomePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    status: str
    detail: str | None = None


class CoveragePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    required_coverage_complete: bool
    mandatory_missing: tuple[str, ...] = ()
    optional_missing: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    unreviewable: tuple[str, ...] = ()
    reviewed: tuple[str, ...] = ()


class CliResultDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["mergegate.cli.result/v1"] = Field(
        alias="schema",
        default="mergegate.cli.result/v1",
    )
    gate_state: str
    source_repository: str
    target_ref: str
    target_head_oid: str
    proposed_ref: str
    proposed_head_oid: str
    merge_tree_oid: str | None
    review_policy_version: PolicyVersionPayload
    compute_policy_version: PolicyVersionPayload
    stage_outcomes: tuple[StageOutcomePayload, ...]
    findings: tuple[dict[str, Any], ...]
    coverage: CoveragePayload
    summary: str
    error_detail: str | None = None


def cli_result_document(report: ReviewReport) -> CliResultDocument:
    return CliResultDocument.model_validate(
        {
            "schema": "mergegate.cli.result/v1",
            "gate_state": report.gate_state.value,
            "source_repository": report.resolved.source_repository,
            "target_ref": report.resolved.target_ref,
            "target_head_oid": report.resolved.target_head_oid,
            "proposed_ref": report.resolved.proposed_ref,
            "proposed_head_oid": report.resolved.proposed_head_oid,
            "merge_tree_oid": report.merge_tree_oid,
            "review_policy_version": {
                "semver": report.review_policy_version.semver,
                "sha256": report.review_policy_version.sha256,
            },
            "compute_policy_version": {
                "semver": report.compute_policy_version.semver,
                "sha256": report.compute_policy_version.sha256,
            },
            "stage_outcomes": [
                {
                    "stage": outcome.stage.value,
                    "status": outcome.status.value,
                    "detail": outcome.detail,
                }
                for outcome in report.execution.outcomes
            ],
            "findings": [finding.model_dump(mode="json") for finding in report.findings],
            "coverage": (
                {
                    "required_coverage_complete": report.coverage.required_coverage_complete,
                    "mandatory_missing": list(report.coverage.mandatory_missing),
                    "optional_missing": list(report.coverage.optional_missing),
                    "excluded": list(report.coverage.excluded),
                    "unreviewable": list(report.coverage.unreviewable),
                    "reviewed": list(report.coverage.reviewed),
                }
                if report.coverage is not None
                else {
                    "required_coverage_complete": False,
                    "mandatory_missing": [],
                    "optional_missing": [],
                    "excluded": [],
                    "unreviewable": [],
                    "reviewed": [],
                }
            ),
            "summary": report.summary,
            "error_detail": report.error_detail,
        }
    )


def cli_result_schema() -> dict[str, Any]:
    return load_schema(CLI_RESULT_SCHEMA_ID)
