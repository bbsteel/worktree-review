"""Machine-readable CLI result ``worktree-review.cli.result/v1`` (PRD §19; D10)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.findings import Finding
from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ProposedSource,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.provider import UsageKind, UsageRecord
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    CoverageRecord,
    DimensionOutcome,
    ExecutionRecord,
    GateState,
    ReviewCallPlan,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from worktree_review.schemas import CLI_RESULT_SCHEMA_ID, load_schema


class PolicyVersionPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    semver: str
    sha256: str


class ComputePolicyDisclosurePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    data_destination: str
    known_retention: str
    provider_configuration_fingerprint: str | None = None


class StageOutcomePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    status: str
    detail: str | None = None


class DimensionOutcomePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension_id: str
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


class UsagePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: str | None = None
    provider: str
    model: str
    note: str | None = None


class ReviewCallPlanPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_count: int
    estimated_input_tokens: int | None = None
    max_output_tokens_per_call: int


class RequestKeyPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_repository: str
    target_ref: str
    target_head_oid: str
    proposed_head_oid: str
    review_policy_version: PolicyVersionPayload


class ReviewIdentityPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    merge_tree_oid: str
    review_policy_version: PolicyVersionPayload


class CliResultDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: Literal["worktree-review.cli.result/v1"] = Field(
        alias="schema",
        default="worktree-review.cli.result/v1",
    )
    gate_state: str
    attempt_id: str
    request_key: RequestKeyPayload
    review_identity: ReviewIdentityPayload | None = None
    source_repository: str
    target_ref: str
    target_head_oid: str
    proposed_ref: str
    proposed_source: str
    proposed_head_oid: str
    merge_tree_oid: str | None
    review_policy_version: PolicyVersionPayload
    compute_policy_version: PolicyVersionPayload
    compute_policy_disclosure: ComputePolicyDisclosurePayload
    stage_outcomes: tuple[StageOutcomePayload, ...]
    dimension_outcomes: tuple[DimensionOutcomePayload, ...]
    findings: tuple[dict[str, Any], ...]
    draft_findings: tuple[dict[str, Any], ...]
    coverage: CoveragePayload
    usage: tuple[UsagePayload, ...]
    call_plan: ReviewCallPlanPayload | None = None
    summary: str
    error_detail: str | None = None


def cli_result_document(report: ReviewReport) -> CliResultDocument:
    return CliResultDocument.model_validate(
        {
            "schema": "worktree-review.cli.result/v1",
            "gate_state": report.gate_state.value,
            "attempt_id": report.attempt_id,
            "request_key": {
                "source_repository": report.request_key.source_repository,
                "target_ref": report.request_key.target_ref,
                "target_head_oid": report.request_key.target_head_oid,
                "proposed_head_oid": report.request_key.proposed_head_oid,
                "review_policy_version": {
                    "semver": report.request_key.review_policy_version.semver,
                    "sha256": report.request_key.review_policy_version.sha256,
                },
            },
            "review_identity": (
                None
                if report.review_identity is None
                else {
                    "merge_tree_oid": report.review_identity.candidate.merge_tree_oid,
                    "review_policy_version": {
                        "semver": report.review_identity.review_policy_version.semver,
                        "sha256": report.review_identity.review_policy_version.sha256,
                    },
                }
            ),
            "source_repository": report.resolved.source_repository,
            "target_ref": report.resolved.target_ref,
            "target_head_oid": report.resolved.target_head_oid,
            "proposed_ref": report.resolved.proposed_ref,
            "proposed_source": report.resolved.proposed_source.value,
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
            "compute_policy_disclosure": {
                "provider": report.compute_policy_disclosure.provider,
                "model": report.compute_policy_disclosure.model,
                "data_destination": report.compute_policy_disclosure.data_destination,
                "known_retention": report.compute_policy_disclosure.known_retention,
                "provider_configuration_fingerprint": (
                    report.compute_policy_disclosure.provider_configuration_fingerprint
                ),
            },
            "stage_outcomes": [
                {
                    "stage": outcome.stage.value,
                    "status": outcome.status.value,
                    "detail": outcome.detail,
                }
                for outcome in report.execution.outcomes
            ],
            "dimension_outcomes": [
                {
                    "dimension_id": outcome.dimension_id,
                    "status": outcome.status.value,
                    "detail": outcome.detail,
                }
                for outcome in report.dimension_outcomes
            ],
            "findings": [finding.model_dump(mode="json") for finding in report.findings],
            "draft_findings": [
                finding.model_dump(mode="json") for finding in report.draft_findings
            ],
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
            "usage": [
                {
                    "kind": record.kind.value,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "cost_usd": None if record.cost_usd is None else str(record.cost_usd),
                    "provider": record.provider,
                    "model": record.model,
                    "note": record.note,
                }
                for record in report.usage
            ],
            "call_plan": (
                None
                if report.call_plan is None
                else {
                    "call_count": report.call_plan.call_count,
                    "estimated_input_tokens": report.call_plan.estimated_input_tokens,
                    "max_output_tokens_per_call": report.call_plan.max_output_tokens_per_call,
                }
            ),
            "summary": report.summary,
            "error_detail": report.error_detail,
        }
    )


def cli_result_schema() -> dict[str, Any]:
    return load_schema(CLI_RESULT_SCHEMA_ID)


def parse_cli_result_document(raw: str | dict[str, Any]) -> CliResultDocument:
    if isinstance(raw, str):
        return CliResultDocument.model_validate_json(raw)
    return CliResultDocument.model_validate(raw)


def review_report_from_cli_result(document: CliResultDocument) -> ReviewReport:
    """Rebuild the surface-neutral report from the canonical persisted document."""

    def policy(payload: PolicyVersionPayload) -> PolicyVersionIdentity:
        return PolicyVersionIdentity(semver=payload.semver, sha256=payload.sha256)

    request_key = ReviewRequestKey(
        source_repository=document.request_key.source_repository,
        target_ref=document.request_key.target_ref,
        target_head_oid=document.request_key.target_head_oid,
        proposed_head_oid=document.request_key.proposed_head_oid,
        review_policy_version=policy(document.request_key.review_policy_version),
    )
    identity = None
    if document.review_identity is not None:
        identity = ReviewIdentity(
            candidate=MergeCandidateIdentity(
                source_repository=document.source_repository,
                target_ref=document.target_ref,
                target_head_oid=document.target_head_oid,
                proposed_head_oid=document.proposed_head_oid,
                merge_tree_oid=document.review_identity.merge_tree_oid,
            ),
            review_policy_version=policy(document.review_identity.review_policy_version),
        )
    return ReviewReport(
        gate_state=GateState(document.gate_state),
        attempt_id=document.attempt_id,
        request_key=request_key,
        resolved=ResolvedCommitPair(
            source_repository=document.source_repository,
            target_ref=document.target_ref,
            target_head_oid=document.target_head_oid,
            proposed_ref=document.proposed_ref,
            proposed_head_oid=document.proposed_head_oid,
            proposed_source=ProposedSource(document.proposed_source),
        ),
        merge_tree_oid=document.merge_tree_oid,
        review_identity=identity,
        review_policy_version=policy(document.review_policy_version),
        compute_policy_version=policy(document.compute_policy_version),
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider=document.compute_policy_disclosure.provider,
            model=document.compute_policy_disclosure.model,
            data_destination=document.compute_policy_disclosure.data_destination,
            known_retention=document.compute_policy_disclosure.known_retention,
            provider_configuration_fingerprint=(
                document.compute_policy_disclosure.provider_configuration_fingerprint
            ),
        ),
        execution=ExecutionRecord(
            outcomes=tuple(
                StageOutcome(
                    stage=StageName(item.stage),
                    status=StageStatus(item.status),
                    detail=item.detail,
                )
                for item in document.stage_outcomes
            )
        ),
        findings=tuple(Finding.model_validate(item) for item in document.findings),
        draft_findings=tuple(Finding.model_validate(item) for item in document.draft_findings),
        coverage=CoverageRecord(
            required_coverage_complete=document.coverage.required_coverage_complete,
            mandatory_missing=document.coverage.mandatory_missing,
            optional_missing=document.coverage.optional_missing,
            excluded=document.coverage.excluded,
            unreviewable=document.coverage.unreviewable,
            reviewed=document.coverage.reviewed,
        ),
        dimension_outcomes=tuple(
            DimensionOutcome(
                dimension_id=item.dimension_id,
                status=StageStatus(item.status),
                detail=item.detail,
            )
            for item in document.dimension_outcomes
        ),
        usage=tuple(
            UsageRecord(
                kind=UsageKind(record.kind),
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cost_usd=None if record.cost_usd is None else Decimal(record.cost_usd),
                provider=record.provider,
                model=record.model,
                note=record.note,
            )
            for record in document.usage
        ),
        call_plan=(
            None
            if document.call_plan is None
            else ReviewCallPlan(
                call_count=document.call_plan.call_count,
                estimated_input_tokens=document.call_plan.estimated_input_tokens,
                max_output_tokens_per_call=document.call_plan.max_output_tokens_per_call,
            )
        ),
        summary=document.summary,
        error_detail=document.error_detail,
    )


def load_review_report_from_cli_result(raw: str | dict[str, Any]) -> ReviewReport:
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return review_report_from_cli_result(parse_cli_result_document(raw))
        if isinstance(loaded, dict) and loaded.get("schema") == "worktree-review.cli.result/v1":
            return review_report_from_cli_result(parse_cli_result_document(loaded))
        return ReviewReport.model_validate(loaded)
    if raw.get("schema") == "worktree-review.cli.result/v1":
        return review_report_from_cli_result(parse_cli_result_document(raw))
    return ReviewReport.model_validate(raw)
