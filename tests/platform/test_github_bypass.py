"""GitHub finding bypass: authorization, domain rules, invalidation, sync (PRD §16, D9).

Adapted onto the P3 design: frozen Review Policy documents, standing-first
replay checks, per-bypass standing revisions, and durable Check sync intents.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
    DimensionOutcome,
    ExecutionRecord,
    GateState,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.github.authz import GitHubRoleBypassAuthorizer
from worktree_review.platform.github.bypass import (
    BypassAuthorizationError,
    BypassAuthorizationUnavailableError,
    BypassRejectionError,
    BypassRequest,
    GitHubBypassCoordinator,
    risk_digest_for_snapshot,
    risk_snapshot_for_finding,
    validate_bypass_reason,
)
from worktree_review.platform.github.errors import GitHubApiError
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.triggers import build_frozen_execution_snapshot
from worktree_review.server.state import (
    BypassStatus,
    CheckSyncStatus,
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
)

CHECK_RUN_ID = 98765


def _locator() -> GitHubChangeRequestLocator:
    return GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )


def _request_key(
    policy_version: PolicyVersionIdentity,
    *,
    proposed_head_oid: str = "b" * 40,
) -> ReviewRequestKey:
    return ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid=proposed_head_oid,
        review_policy_version=policy_version,
    )


def _identity(request_key: ReviewRequestKey) -> ReviewIdentity:
    return ReviewIdentity(
        candidate=MergeCandidateIdentity(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_head_oid=request_key.proposed_head_oid,
            merge_tree_oid="c" * 40,
        ),
        review_policy_version=request_key.review_policy_version,
    )


def _finding(
    fingerprint: str,
    *,
    severity: Severity = Severity.MAJOR,
    evidence_band: EvidenceBand = EvidenceBand.SUPPORTED,
) -> Finding:
    return Finding(
        fingerprint=fingerprint,
        severity=severity,
        evidence_band=evidence_band,
        problem_statement=f"problem {fingerprint}",
        expected_impact="merge candidate impact",
        evidence_spans=(
            EvidenceSpan(
                path="src/webhooks/verify.py",
                start_line=74,
                end_line=80,
                quoted_text="signature = headers.get('x-sig')",
                source=EvidenceSource.REVIEW_WORKTREE,
                snapshot_identity="c" * 40,
            ),
        ),
        repair_guidance="reject unsigned requests",
        dimension_id="correctness",
    )


_COMPLETE_OUTCOMES = tuple(
    StageOutcome(stage=stage, status=StageStatus.COMPLETED)
    for stage in (
        StageName.DERIVE_IDENTITY,
        StageName.CONSTRUCT_MERGE,
        StageName.GATHER_CONTEXT,
        StageName.RUN_DIMENSIONS,
        StageName.VERIFY_DEDUP,
        StageName.CHECK_COMPLETENESS,
        StageName.EVALUATE_GATE,
    )
)


def _report(
    attempt_id: str,
    request_key: ReviewRequestKey,
    *,
    gate_state: GateState = GateState.BLOCKED,
    findings: tuple[Finding, ...] = (),
    complete: bool = True,
) -> ReviewReport:
    return ReviewReport(
        gate_state=gate_state,
        attempt_id=attempt_id,
        request_key=request_key,
        resolved=ResolvedCommitPair(
            source_repository=request_key.source_repository,
            target_ref=request_key.target_ref,
            target_head_oid=request_key.target_head_oid,
            proposed_ref="feature",
            proposed_head_oid=request_key.proposed_head_oid,
        ),
        merge_tree_oid="c" * 40,
        review_identity=None if gate_state is GateState.ERROR else _identity(request_key),
        review_policy_version=request_key.review_policy_version,
        compute_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="e" * 64),
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="claude",
            data_destination="https://api.anthropic.com",
            known_retention="none",
        ),
        execution=ExecutionRecord(outcomes=_COMPLETE_OUTCOMES if complete else ()),
        findings=findings,
        coverage=CoverageRecord(
            required_coverage_complete=complete and gate_state is not GateState.ERROR,
            reviewed=("src/webhooks/verify.py",),
        ),
        dimension_outcomes=(
            (
                DimensionOutcome(dimension_id="correctness", status=StageStatus.COMPLETED)
                if gate_state is not GateState.ERROR
                else DimensionOutcome(dimension_id="correctness", status=StageStatus.FAILED)
            ),
        ),
        summary="review complete",
    )


class _StaticRoleLookup:
    def __init__(self, role: str | None, *, raises: bool = False) -> None:
        self.role = role
        self.raises = raises

    async def repository_role(
        self, *, installation_id: int, repository: str, actor: str
    ) -> str | None:
        if self.raises:
            raise GitHubApiError("github unreachable")
        return self.role


class _Fixture:
    def __init__(self, policy_dir: Path, *, role: str | None = "admin") -> None:
        self.policy_dir = policy_dir
        self.state = InMemoryAuthoritativeAttemptStore()
        self.store = InMemoryGitHubReviewStore()
        self.locator = _locator()
        self.set_role(role)

    def set_role(self, role: str | None, *, raises: bool = False) -> None:
        self.coordinator = GitHubBypassCoordinator(
            state=self.state,
            github_store=self.store,
            authorizer=GitHubRoleBypassAuthorizer(_StaticRoleLookup(role, raises=raises)),
            review_policy_path=self.policy_dir / "review-policy.yaml",
        )

    async def start_blocked_attempt(
        self,
        *,
        gate_state: GateState = GateState.BLOCKED,
        findings: tuple[Finding, ...] = (),
        complete: bool = True,
        with_check: bool = True,
        freeze_policy_document: bool = True,
    ) -> str:
        from worktree_review.core.policy import load_review_policy

        _policy, policy_version = load_review_policy(self.policy_dir / "review-policy.yaml")
        request_key = _request_key(policy_version)
        lease = await self.state.start_authoritative_attempt(
            change_request=self.locator,
            request_key=request_key,
        )
        self.last_request_key = request_key
        report = _report(
            lease.attempt_id,
            request_key,
            gate_state=gate_state,
            findings=findings,
            complete=complete,
        )
        if report.review_identity is not None:
            await self.state.record_review_identity(
                attempt_id=lease.attempt_id,
                review_identity=report.review_identity,
            )
        await self.state.claim_attempt_job(lease.attempt_id)
        if freeze_policy_document:
            snapshot = build_frozen_execution_snapshot(
                attempt_id=lease.attempt_id,
                change_request=self.locator,
                request_key=request_key,
                proposed_ref="feature",
                review_policy_path=self.policy_dir / "review-policy.yaml",
                compute_policy_path=self.policy_dir / "compute-policy.yaml",
            )
        else:
            from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot

            snapshot = AttemptExecutionSnapshot(
                attempt_id=lease.attempt_id,
                change_request=self.locator,
                request_key=request_key,
                proposed_ref="feature",
                review_policy_semver=policy_version.semver,
                review_policy_sha256=policy_version.sha256,
                compute_policy_semver="1.0.0",
                compute_policy_sha256="e" * 64,
            )
        await self.store.save_execution_snapshot(snapshot)
        if with_check:
            await self.store.set_check_run_id(lease.attempt_id, CHECK_RUN_ID)
            from worktree_review.application.lifecycle import PublicationStatus

            await self.store.mark_publication(lease.attempt_id, status=PublicationStatus.PUBLISHED)
        await self.store.save_review_result(
            lease.attempt_id,
            cli_result_document(report).model_dump_json(by_alias=True),
        )
        await self.state.publish_if_authoritative(
            attempt_id=lease.attempt_id,
            request_key=request_key,
            review_identity=report.review_identity,
            gate_state=gate_state,
        )
        return lease.attempt_id

    def request(
        self,
        attempt_id: str,
        fingerprint: str,
        *,
        actor_login: str = "maintainer",
        reason: str = "accepted risk: upstream WAF blocks unsigned calls",
    ) -> BypassRequest:
        return BypassRequest(
            attempt_id=attempt_id,
            finding_fingerprint=fingerprint,
            actor_id=123456,
            actor_login=actor_login,
            reason=reason,
        )


@pytest.mark.asyncio
async def test_bypass_last_blocking_finding_transitions_standing_gate(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))

    accepted = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    result = accepted.result

    assert result.gate_transitioned is True
    assert result.standing_gate_state is GateState.PASSED_WITH_BYPASS
    assert result.record.actor_id == 123456
    assert result.record.actor_login == "maintainer"
    assert result.record.review_identity == _identity(fixture.last_request_key)
    assert result.check_sync_status is CheckSyncStatus.QUEUED
    current = await fixture.state.get_change_request_state(fixture.locator)
    assert current.standing_gate_state is GateState.PASSED_WITH_BYPASS
    assert current.standing_revision == result.standing_revision
    event_types = [event["event_type"] for event in await fixture.state.audit_events()]
    assert "bypass_authorized" in event_types
    assert "gate_transition" in event_types
    assert "check_sync_queued" in event_types


@pytest.mark.asyncio
async def test_bypass_with_remaining_blocking_finding_keeps_blocked(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"), _finding("fp-2")))

    first = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    assert first.result.gate_transitioned is False
    assert first.result.standing_gate_state is GateState.BLOCKED
    assert first.result.remaining_blocking_count == 1

    second = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-2"))
    assert second.result.gate_transitioned is True
    assert second.result.standing_gate_state is GateState.PASSED_WITH_BYPASS
    # Every accepted bypass moves the standing revision and enqueues a fresh
    # sync intent; the earlier intent is terminal-superseded.
    assert second.result.standing_revision > first.result.standing_revision
    latest = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    assert latest is not None
    assert latest.standing_revision == second.result.standing_revision
    assert latest.status is CheckSyncStatus.QUEUED


@pytest.mark.asyncio
async def test_unauthorized_actor_is_denied_and_audited(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir, role="read")
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))

    with pytest.raises(BypassAuthorizationError):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    assert await fixture.state.list_bypasses(attempt_id=attempt_id) == ()
    current = await fixture.state.get_change_request_state(fixture.locator)
    assert current.standing_gate_state is GateState.BLOCKED
    events = await fixture.state.audit_events()
    denied = [event for event in events if event["event_type"] == "bypass_denied"]
    assert len(denied) == 1
    assert denied[0]["actor_id"] == 123456
    assert denied[0]["actor_login"] == "maintainer"


@pytest.mark.asyncio
async def test_authorizer_outage_is_unavailable_not_denied(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    fixture.set_role(None, raises=True)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))

    with pytest.raises(BypassAuthorizationUnavailableError):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    # Nothing was written: no bypass, no denial audit, no standing change.
    assert await fixture.state.list_bypasses(attempt_id=attempt_id) == ()
    events = await fixture.state.audit_events()
    assert not [event for event in events if event["event_type"].startswith("bypass_")]


@pytest.mark.asyncio
async def test_error_gate_cannot_be_bypassed(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(
        gate_state=GateState.ERROR,
        findings=(_finding("fp-1"),),
    )

    with pytest.raises(BypassRejectionError, match="bypass_gate_error"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))


@pytest.mark.asyncio
async def test_incomplete_report_cannot_be_bypassed(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),), complete=False)

    with pytest.raises(BypassRejectionError, match="bypass_gate_error"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))


@pytest.mark.asyncio
async def test_non_blocking_finding_cannot_be_bypassed(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    minor = _finding("fp-minor", severity=Severity.MINOR)
    insufficient = _finding("fp-insufficient", evidence_band=EvidenceBand.INSUFFICIENT)
    attempt_id = await fixture.start_blocked_attempt(
        findings=(_finding("fp-1"), minor, insufficient)
    )

    with pytest.raises(BypassRejectionError, match="bypass_not_blocking"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-minor"))
    with pytest.raises(BypassRejectionError, match="bypass_not_blocking"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-insufficient"))


@pytest.mark.asyncio
async def test_unknown_fingerprint_and_attempt_are_rejected(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))

    with pytest.raises(BypassRejectionError, match="finding_not_found"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-missing"))
    with pytest.raises(BypassRejectionError, match="attempt_not_found"):
        await fixture.coordinator.request_bypass(
            fixture.request("00000000-dead-beef-0000-000000000000", "fp-1")
        )


@pytest.mark.asyncio
async def test_superseded_attempt_cannot_be_bypassed(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.state.start_authoritative_attempt(
        change_request=fixture.locator,
        request_key=fixture.last_request_key,
    )

    with pytest.raises(BypassRejectionError, match="bypass_not_standing"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))


def test_reason_validation_bounds_and_content() -> None:
    assert validate_bypass_reason("  ok reason  ") == "ok reason"
    for bad in (
        "   ",
        "x" * 2001,
        "line\n```code```\nline",
        "x" * 501,
        "token ghp_abcdefghijklmnop0123 leaked",
    ):
        with pytest.raises(BypassRejectionError, match="bypass_reason_invalid"):
            validate_bypass_reason(bad)


@pytest.mark.asyncio
async def test_policy_change_rejects_bypass_for_legacy_snapshot(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(
        findings=(_finding("fp-1"),), freeze_policy_document=False
    )
    # Drift the trusted file after the (legacy, unfrozen) snapshot was taken.
    policy_path = policy_dir / "review-policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )

    with pytest.raises(BypassRejectionError, match="bypass_policy_changed"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))


@pytest.mark.asyncio
async def test_frozen_policy_document_never_reads_the_drifted_file(policy_dir: Path) -> None:
    """Freeze contract: once the snapshot carries the policy document, the
    trusted file on disk is never re-read — it may have legitimately changed
    for newer Attempts (P3-0). Drift invalidates standing via triggers, not
    via the bypass path."""

    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    policy_path = policy_dir / "review-policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )

    accepted = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    assert accepted.result.standing_gate_state is GateState.PASSED_WITH_BYPASS


@pytest.mark.asyncio
async def test_unpublished_attempt_cannot_be_bypassed(policy_dir: Path) -> None:
    """No published Check, no bypass: the standing decision must already live
    on GitHub before risk can be accepted on top of it (P3 §5.1.2)."""

    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),), with_check=False)
    with pytest.raises(BypassRejectionError, match="bypass_not_standing"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    # Nothing was written.
    assert await fixture.state.list_bypasses(attempt_id=attempt_id) == ()


@pytest.mark.asyncio
async def test_tampered_frozen_policy_document_fails_closed(policy_dir: Path) -> None:
    from worktree_review.core.policy import load_review_policy

    fixture = _Fixture(policy_dir)
    _policy, policy_version = load_review_policy(policy_dir / "review-policy.yaml")
    request_key = _request_key(policy_version)
    lease = await fixture.state.start_authoritative_attempt(
        change_request=fixture.locator, request_key=request_key
    )
    report = _report(lease.attempt_id, request_key, findings=(_finding("fp-1"),))
    await fixture.state.record_review_identity(
        attempt_id=lease.attempt_id, review_identity=report.review_identity
    )
    await fixture.state.claim_attempt_job(lease.attempt_id)
    snapshot = build_frozen_execution_snapshot(
        attempt_id=lease.attempt_id,
        change_request=fixture.locator,
        request_key=request_key,
        proposed_ref="feature",
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
    )
    # Tamper: keep the identity, weaken the frozen document itself.
    assert snapshot.review_policy_document is not None
    tampered = dict(snapshot.review_policy_document)
    tampered["blocking_severities"] = ["critical"]
    await fixture.store.save_execution_snapshot(
        snapshot.model_copy(update={"review_policy_document": tampered})
    )
    from worktree_review.application.lifecycle import PublicationStatus

    await fixture.store.set_check_run_id(lease.attempt_id, CHECK_RUN_ID)
    await fixture.store.mark_publication(lease.attempt_id, status=PublicationStatus.PUBLISHED)
    await fixture.store.save_review_result(
        lease.attempt_id, cli_result_document(report).model_dump_json(by_alias=True)
    )
    await fixture.state.publish_if_authoritative(
        attempt_id=lease.attempt_id,
        request_key=request_key,
        review_identity=report.review_identity,
        gate_state=GateState.BLOCKED,
    )

    with pytest.raises(BypassRejectionError, match="bypass_policy_changed"):
        await fixture.coordinator.request_bypass(fixture.request(lease.attempt_id, "fp-1"))


@pytest.mark.asyncio
async def test_legacy_snapshot_without_frozen_document_still_works(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(
        findings=(_finding("fp-1"),), freeze_policy_document=False
    )

    accepted = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    assert accepted.result.standing_gate_state is GateState.PASSED_WITH_BYPASS


@pytest.mark.asyncio
async def test_replay_returns_original_record_and_conflicts(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    accepted = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    replayed = await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    assert replayed.replayed is True
    assert replayed.result.record == accepted.result.record
    assert len(await fixture.state.list_bypasses(attempt_id=attempt_id)) == 1

    conflicting = fixture.request(attempt_id, "fp-1", reason="a different justification")
    with pytest.raises(BypassRejectionError, match="bypass_conflict"):
        await fixture.coordinator.request_bypass(conflicting)


@pytest.mark.asyncio
async def test_replay_after_retry_is_rejected_not_replayed(policy_dir: Path) -> None:
    """The replay path must re-verify standing first: after a retry the old
    record is invalidated and the new Attempt owns the standing decision."""

    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    await fixture.state.start_authoritative_attempt(
        change_request=fixture.locator,
        request_key=fixture.last_request_key,
    )

    with pytest.raises(BypassRejectionError, match="bypass_not_standing"):
        await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    records = await fixture.state.list_bypasses(attempt_id=attempt_id)
    assert [record.status for record in records] == [BypassStatus.INVALIDATED]


@pytest.mark.asyncio
async def test_same_identity_retry_invalidates_prior_bypass(policy_dir: Path) -> None:
    """No carry-forward this wave: even an identical Request Key re-reviews in
    full and requires fresh risk acceptance (P3 §5.2)."""

    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    await fixture.state.start_authoritative_attempt(
        change_request=fixture.locator,
        request_key=fixture.last_request_key,
    )

    records = await fixture.state.list_bypasses(attempt_id=attempt_id)
    assert [record.status for record in records] == [BypassStatus.INVALIDATED]
    event_types = [event["event_type"] for event in await fixture.state.audit_events()]
    assert "bypass_invalidated" in event_types


@pytest.mark.asyncio
async def test_standing_invalidation_expires_bypass_and_sync(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    await fixture.state.invalidate_standing_decision(fixture.locator, reason="converted_to_draft")

    records = await fixture.state.list_bypasses(attempt_id=attempt_id)
    assert [record.status for record in records] == [BypassStatus.INVALIDATED]
    assert records[0].invalidation_reason == "converted_to_draft"
    latest = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.SUPERSEDED


def test_risk_snapshot_binds_evidence_without_quoted_source() -> None:
    snapshot = risk_snapshot_for_finding(_finding("fp-1"))

    assert snapshot["severity"] == "major"
    assert snapshot["evidence_band"] == "supported"
    assert snapshot["evidence_spans"] == [
        {
            "path": "src/webhooks/verify.py",
            "start_line": 74,
            "end_line": 80,
            "source": "review-worktree",
            "snapshot_identity": "c" * 40,
            "change_kind": None,
        }
    ]
    assert "quoted_text" not in str(snapshot)
    assert "headers.get" not in str(snapshot)
    # The digest is stable and covers every field.
    assert risk_digest_for_snapshot(snapshot) == risk_digest_for_snapshot(dict(snapshot))
    other = risk_snapshot_for_finding(_finding("fp-2"))
    assert risk_digest_for_snapshot(other) != risk_digest_for_snapshot(snapshot)


class _RecordingChecks:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.updates: list[dict[str, object]] = []

    async def create_check_run(self, *, repository: str, payload: object) -> int:
        return CHECK_RUN_ID

    async def update_check_run(
        self, *, repository: str, check_run_id: int, payload: object
    ) -> None:
        if self.fail:
            raise GitHubApiError("check update failed")
        self.updates.append({"repository": repository, "check_run_id": check_run_id})


@pytest.mark.asyncio
async def test_standing_check_sync_patches_the_same_check(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    checks = _RecordingChecks()
    publisher = GitHubCheckPublisher(state=fixture.state, github_store=fixture.store, checks=checks)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    intent = await fixture.state.claim_standing_check_sync(
        now=__import__("datetime").datetime.now(__import__("datetime").UTC),
        lease_seconds=120.0,
    )
    assert intent is not None
    assert intent.check_run_id == CHECK_RUN_ID
    await publisher.deliver_standing_check_sync(intent)

    assert checks.updates == [{"repository": "octo/example", "check_run_id": CHECK_RUN_ID}]
    latest = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.PUBLISHED
    event_types = [event["event_type"] for event in await fixture.state.audit_events()]
    assert "check_sync_published" in event_types


@pytest.mark.asyncio
async def test_standing_check_sync_failure_backs_off_then_fails(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    checks = _RecordingChecks(fail=True)
    publisher = GitHubCheckPublisher(state=fixture.state, github_store=fixture.store, checks=checks)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    intent = await fixture.state.claim_standing_check_sync(now=now, lease_seconds=120.0)
    assert intent is not None
    await publisher.deliver_standing_check_sync(intent)
    after_failure = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    assert after_failure is not None
    assert after_failure.status is CheckSyncStatus.QUEUED
    assert after_failure.next_retry_at is not None
    assert after_failure.last_error

    # Exhaust the bounded budget: the intent lands in queryable FAILED with an
    # explicit audit event, and the database decision is untouched.
    for _ in range(8):
        current = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
        assert current is not None
        await fixture.state.mark_standing_check_sync(
            current.intent_id, status=CheckSyncStatus.QUEUED, next_retry_at=None
        )
        intent = await fixture.state.claim_standing_check_sync(now=now, lease_seconds=120.0)
        assert intent is not None
        await publisher.deliver_standing_check_sync(intent)
        current = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
        assert current is not None
        if current.status is CheckSyncStatus.FAILED:
            break
    assert current.status is CheckSyncStatus.FAILED
    current_state = await fixture.state.get_change_request_state(fixture.locator)
    assert current_state.standing_gate_state is GateState.PASSED_WITH_BYPASS
    event_types = [event["event_type"] for event in await fixture.state.audit_events()]
    assert "check_sync_failed" in event_types


@pytest.mark.asyncio
async def test_stale_revision_sync_is_superseded_not_delivered(policy_dir: Path) -> None:
    fixture = _Fixture(policy_dir)
    checks = _RecordingChecks()
    publisher = GitHubCheckPublisher(state=fixture.state, github_store=fixture.store, checks=checks)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"), _finding("fp-2")))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-2"))

    # The first intent was superseded by the second; only the newest revision
    # is claimable, and delivering a stale intent PATCHes nothing.
    from datetime import UTC, datetime

    first_intent = await fixture.state.claim_standing_check_sync(
        now=datetime.now(UTC), lease_seconds=120.0
    )
    assert first_intent is not None
    latest = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    assert first_intent.standing_revision == latest.standing_revision  # type: ignore[union-attr]
    assert len(checks.updates) == 0
    await publisher.deliver_standing_check_sync(first_intent)
    assert len(checks.updates) == 1


@pytest.mark.asyncio
async def test_bypass_and_retry_race_stays_consistent(policy_dir: Path) -> None:
    """A concurrent retry either lets the bypass land (then invalidates it) or
    wins first (then the bypass conflicts); no deadlock, no torn state."""
    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))

    async def _retry() -> None:
        await fixture.state.start_authoritative_attempt(
            change_request=fixture.locator,
            request_key=fixture.last_request_key,
        )

    async def _bypass() -> str:
        try:
            await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))
            return "applied"
        except BypassRejectionError:
            return "rejected"

    bypass_outcome, _ = await asyncio.gather(_bypass(), _retry())
    records = await fixture.state.list_bypasses(attempt_id=attempt_id)
    if bypass_outcome == "applied":
        assert [record.status for record in records] == [BypassStatus.INVALIDATED]
    else:
        assert records == ()
    current = await fixture.state.get_change_request_state(fixture.locator)
    assert current.authoritative_attempt_id != attempt_id


@pytest.mark.asyncio
async def test_detail_projection_reports_core_and_standing_side_by_side(
    policy_dir: Path,
) -> None:
    """P3 §8.2: the Detail DTO carries the immutable Core gate, the standing
    decision, per-finding bypass records, and the Check sync status."""

    from worktree_review.application.lifecycle import PublicationStatus
    from worktree_review.platform.github.frozen_policy import resolve_frozen_review_policy
    from worktree_review.platform.web.presenters import present_github_review_run

    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"), _finding("fp-2")))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    snapshot = await fixture.store.get_execution_snapshot(attempt_id)
    assert snapshot is not None
    change_state = await fixture.state.get_change_request_state(fixture.locator)
    result_json = await fixture.store.get_review_result(attempt_id)
    latest_sync = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    blocking_policy = resolve_frozen_review_policy(
        snapshot, legacy_review_policy_path=policy_dir / "review-policy.yaml"
    )
    dto = present_github_review_run(
        snapshot=snapshot,
        change_state=change_state,
        publication_status=PublicationStatus.PUBLISHED,
        check_run_id=CHECK_RUN_ID,
        result_json=result_json,
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        bypasses=await fixture.state.list_bypasses(attempt_id=attempt_id),
        check_sync_status=None if latest_sync is None else latest_sync.status.value,
        bypass_capability="available",
        actor_authenticated=True,
        bypass_preconditions_met=True,
        blocking_policy=blocking_policy,
        review_policy_trusted=True,
    )

    # The immutable report stays Blocked; the standing decision is separate.
    assert dto["core_gate_state"] == "Blocked"
    assert dto["standing_gate_state"] == "Blocked"  # fp-2 still blocks
    assert dto["bypass_state"] == "active"
    assert dto["standing_revision"] >= 1
    assert dto["check_sync_status"] == "queued"
    assert dto["bypass_capability"] == "available"
    assert dto["gate"]["remaining_blocking_fingerprints"] == ["fp-2"]
    findings = {finding["fingerprint"]: finding for finding in dto["findings"]}
    assert findings["fp-1"]["bypass_record"]["status"] == "active"
    assert findings["fp-1"]["bypass_record"]["actor_login"] == "maintainer"
    assert findings["fp-1"]["bypass_record"]["reason"].startswith("accepted risk")
    assert findings["fp-2"]["bypass_record"] is None
    # The original finding content survives the bypass untouched.
    assert findings["fp-1"]["problem_statement"] == "problem fp-1"
    assert dto["review_policy_trusted"] is True
    assert dto["available_actions"]["bypass"]["enabled"] is True


@pytest.mark.asyncio
async def test_detail_projection_fails_closed_when_frozen_policy_untrusted(
    policy_dir: Path,
) -> None:
    """Untrusted Policy must not invent Critical/Major blockers or enable Bypass."""

    from worktree_review.application.lifecycle import PublicationStatus
    from worktree_review.platform.web.presenters import present_github_review_run

    fixture = _Fixture(policy_dir)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    snapshot = await fixture.store.get_execution_snapshot(attempt_id)
    assert snapshot is not None
    # Tamper the frozen document identity while leaving the bytes parseable.
    snapshot = snapshot.model_copy(update={"review_policy_sha256": "0" * 64})
    change_state = await fixture.state.get_change_request_state(fixture.locator)
    result_json = await fixture.store.get_review_result(attempt_id)
    dto = present_github_review_run(
        snapshot=snapshot,
        change_state=change_state,
        publication_status=PublicationStatus.PUBLISHED,
        check_run_id=CHECK_RUN_ID,
        result_json=result_json,
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        bypass_capability="available",
        actor_authenticated=True,
        bypass_preconditions_met=False,
        blocking_policy=None,
        review_policy_trusted=False,
    )
    assert dto["review_policy_trusted"] is False
    assert dto["gate"]["blocking_fingerprints"] == []
    assert dto["available_actions"]["bypass"]["enabled"] is False


@pytest.mark.asyncio
async def test_sync_crash_after_patch_redelivers_idempotently(policy_dir: Path) -> None:
    """Crash window: the PATCH reached GitHub but the mark was lost. The lease
    expires, the intent is reclaimed, and the same Check ID is PATCHed again —
    remote convergence without a parallel Check (P3 §12.3)."""

    fixture = _Fixture(policy_dir)
    checks = _RecordingChecks()
    publisher = GitHubCheckPublisher(state=fixture.state, github_store=fixture.store, checks=checks)
    attempt_id = await fixture.start_blocked_attempt(findings=(_finding("fp-1"),))
    await fixture.coordinator.request_bypass(fixture.request(attempt_id, "fp-1"))

    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    intent = await fixture.state.claim_standing_check_sync(now=now, lease_seconds=120.0)
    assert intent is not None
    # Simulate: remote PATCH succeeded, then the process died before marking.
    await checks.update_check_run(
        repository="octo/example",
        check_run_id=CHECK_RUN_ID,
        payload=None,  # type: ignore[arg-type]
    )
    assert len(checks.updates) == 1

    # Lease expires; the sweeper reclaims and redelivers to the same Check.
    reclaimed = await fixture.state.claim_standing_check_sync(
        now=now + timedelta(seconds=121), lease_seconds=120.0
    )
    assert reclaimed is not None
    assert reclaimed.intent_id == intent.intent_id
    await publisher.deliver_standing_check_sync(reclaimed)
    assert checks.updates[-1]["check_run_id"] == CHECK_RUN_ID
    assert len(checks.updates) == 2
    latest = await fixture.state.latest_standing_check_sync(attempt_id=attempt_id)
    assert latest is not None
    assert latest.status is CheckSyncStatus.PUBLISHED
