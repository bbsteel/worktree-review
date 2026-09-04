from __future__ import annotations

import pytest

from worktree_review.core.findings import (
    EvidenceBand,
    EvidenceSource,
    EvidenceSpan,
    Finding,
    Severity,
)
from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    CoverageRecord,
    ExecutionRecord,
    GateState,
    ReviewReport,
)
from worktree_review.platform.github.checks import (
    ATTEMPT_FINGERPRINT_LENGTH,
    AnnotationLevel,
    CheckRunAnnotation,
    CheckRunConclusion,
    CheckRunPayload,
    CheckRunStatus,
    annotation_level_for_severity,
    attempt_fingerprint,
    build_check_run_payload,
    build_check_run_payload_batches,
    publish_check_run,
)


def _report(
    *,
    gate_state: GateState,
    findings: tuple[Finding, ...] = (),
    draft_findings: tuple[Finding, ...] = (),
) -> ReviewReport:
    policy_version = PolicyVersionIdentity(semver="1.0.0", sha256="a" * 64)
    resolved = ResolvedCommitPair(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="b" * 40,
        proposed_ref="feature",
        proposed_head_oid="c" * 40,
    )
    candidate = MergeCandidateIdentity(
        source_repository=resolved.source_repository,
        target_ref=resolved.target_ref,
        target_head_oid=resolved.target_head_oid,
        proposed_head_oid=resolved.proposed_head_oid,
        merge_tree_oid="d" * 40,
    )
    request_key = ReviewRequestKey(
        source_repository=resolved.source_repository,
        target_ref=resolved.target_ref,
        target_head_oid=resolved.target_head_oid,
        proposed_head_oid=resolved.proposed_head_oid,
        review_policy_version=policy_version,
    )
    return ReviewReport(
        gate_state=gate_state,
        attempt_id="attempt-123",
        request_key=request_key,
        resolved=resolved,
        merge_tree_oid=candidate.merge_tree_oid,
        review_identity=ReviewIdentity(
            candidate=candidate,
            review_policy_version=policy_version,
        ),
        review_policy_version=policy_version,
        compute_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="e" * 64),
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="scripted",
            data_destination="https://api.anthropic.com",
            known_retention="test retention",
        ),
        execution=ExecutionRecord(),
        findings=findings,
        draft_findings=draft_findings,
        coverage=CoverageRecord(required_coverage_complete=True),
        summary="Review completed.",
    )


def _finding(*, problem_statement: str = "broken contract") -> Finding:
    return Finding(
        fingerprint="f" * 64,
        severity=Severity.MAJOR,
        evidence_band=EvidenceBand.SUPPORTED,
        problem_statement=problem_statement,
        expected_impact="request fails",
        evidence_spans=(
            EvidenceSpan(
                path="src/app.py",
                start_line=4,
                end_line=4,
                quoted_text="return result",
                source=EvidenceSource.REVIEW_WORKTREE,
                snapshot_identity="d" * 40,
            ),
        ),
    )


class _RecordingCheckTransport:
    def __init__(self) -> None:
        self.created: list[tuple[str, CheckRunPayload]] = []
        self.updated: list[tuple[str, int, CheckRunPayload]] = []

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        self.created.append((repository, payload))
        return 123

    async def update_check_run(
        self,
        *,
        repository: str,
        check_run_id: int,
        payload: CheckRunPayload,
    ) -> None:
        self.updated.append((repository, check_run_id, payload))


def test_check_payload_maps_terminal_gate_and_embeds_attempt_fingerprint() -> None:
    report = _report(gate_state=GateState.BLOCKED, findings=(_finding(),))

    payload = build_check_run_payload(report, details_url="https://review.test/attempt-123")
    serialized = payload.as_github_payload()

    assert payload.status is CheckRunStatus.COMPLETED
    assert payload.conclusion is CheckRunConclusion.FAILURE
    assert payload.head_sha == "c" * 40
    assert payload.external_id == "worktree-review:attempt-123"
    assert attempt_fingerprint("attempt-123") in payload.output.summary
    assert attempt_fingerprint("attempt-123") in payload.output.text
    assert "src/app.py:4-4" in payload.output.text
    assert "Review Request Key" in payload.output.text
    assert "Review Policy" in payload.output.text
    assert "Compute Policy" in payload.output.text
    assert serialized["output"]
    assert "conclusion" in serialized


def test_error_is_failure_and_draft_findings_are_disclosed_separately() -> None:
    report = _report(
        gate_state=GateState.ERROR,
        draft_findings=(_finding(problem_statement="not yet verified"),),
    )

    payload = build_check_run_payload(report)

    assert payload.conclusion is CheckRunConclusion.FAILURE
    assert "Draft findings (not gate evidence)" in payload.output.text
    assert "not yet verified" in payload.output.text


def test_non_terminal_gate_has_status_without_conclusion() -> None:
    queued = build_check_run_payload(_report(gate_state=GateState.AWAITING_REVIEW))
    running = build_check_run_payload(_report(gate_state=GateState.IN_PROGRESS))

    assert queued.status is CheckRunStatus.QUEUED
    assert queued.conclusion is None
    assert running.status is CheckRunStatus.IN_PROGRESS
    assert running.conclusion is None
    assert "conclusion" not in queued.as_github_payload()


def test_annotation_level_preserves_core_severity_mapping() -> None:
    assert annotation_level_for_severity(Severity.CRITICAL) is AnnotationLevel.FAILURE
    assert annotation_level_for_severity(Severity.MAJOR) is AnnotationLevel.FAILURE
    assert annotation_level_for_severity(Severity.MINOR) is AnnotationLevel.WARNING
    assert annotation_level_for_severity(Severity.SUGGESTION) is AnnotationLevel.NOTICE


def test_annotation_line_range_is_validated_before_serialization() -> None:
    try:
        CheckRunAnnotation(
            path="src/app.py",
            start_line=2,
            end_line=1,
            annotation_level=AnnotationLevel.FAILURE,
            message="broken",
            title="Worktree Review",
        )
    except ValueError as error:
        assert "end_line" in str(error)
    else:
        raise AssertionError("reversed annotation line range was accepted")


def test_check_payload_batches_are_limited_to_fifty_annotations() -> None:
    annotations = tuple(
        CheckRunAnnotation(
            path="src/app.py",
            start_line=index + 1,
            end_line=index + 1,
            annotation_level=AnnotationLevel.NOTICE,
            message=f"note {index}",
            title="Worktree Review",
        )
        for index in range(51)
    )

    payloads = build_check_run_payload_batches(
        _report(gate_state=GateState.PASSED),
        annotations=annotations,
    )

    assert [len(payload.output.annotations) for payload in payloads] == [50, 1]
    assert payloads[0].output.annotations[0].start_line == 1
    assert payloads[1].output.annotations[0].start_line == 51
    assert len(attempt_fingerprint("attempt-123")) == ATTEMPT_FINGERPRINT_LENGTH


@pytest.mark.asyncio
async def test_publish_check_run_creates_then_updates_annotation_batches() -> None:
    annotations = tuple(
        CheckRunAnnotation(
            path="src/app.py",
            start_line=index + 1,
            end_line=index + 1,
            annotation_level=AnnotationLevel.NOTICE,
            message=f"note {index}",
            title="Worktree Review",
        )
        for index in range(51)
    )
    transport = _RecordingCheckTransport()

    check_run_id = await publish_check_run(
        _report(gate_state=GateState.PASSED),
        transport=transport,
        annotations=annotations,
    )

    assert check_run_id == 123
    assert len(transport.created) == 1
    assert transport.created[0][0] == "octo/example"
    assert len(transport.created[0][1].output.annotations) == 50
    assert len(transport.updated) == 1
    assert transport.updated[0][1] == 123
    assert len(transport.updated[0][2].output.annotations) == 1
