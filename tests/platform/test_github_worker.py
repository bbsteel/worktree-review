from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import head_oid

from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.provider import ScriptedProvider
from worktree_review.platform.github.checks import CheckRunPayload, CheckRunStatus
from worktree_review.platform.github.mirrors import RepositoryMirrorManager
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.github.worker import GitHubReviewWorker, PolicyDriftError
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
)


class _FakeChecks:
    def __init__(self) -> None:
        self.updated: list[CheckRunStatus] = []

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        del repository, payload
        return 1

    async def update_check_run(
        self, *, repository: str, check_run_id: int, payload: CheckRunPayload
    ) -> None:
        del repository, check_run_id
        self.updated.append(payload.status)


def _request_key(oid: str, review_version: PolicyVersionIdentity) -> ReviewRequestKey:
    return ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid=oid,
        proposed_head_oid=oid,
        review_policy_version=review_version,
    )


@pytest.mark.asyncio
async def test_worker_uses_snapshot_and_preallocated_attempt_id(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    _, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    _, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    state = InMemoryAuthoritativeAttemptStore()
    github_store = InMemoryGitHubReviewStore()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = _request_key(oid, review_version)
    lease = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    await github_store.save_execution_snapshot(
        AttemptExecutionSnapshot(
            attempt_id=lease.attempt_id,
            change_request=locator,
            request_key=request_key,
            proposed_ref="HEAD",
            review_policy_semver=review_version.semver,
            review_policy_sha256=review_version.sha256,
            compute_policy_semver=compute_version.semver,
            compute_policy_sha256=compute_version.sha256,
        )
    )
    await github_store.set_check_run_id(lease.attempt_id, 55)
    checks = _FakeChecks()
    worker = GitHubReviewWorker(
        state=state,
        github_store=github_store,
        mirrors=RepositoryMirrorManager(tmp_path / "mirrors"),
        checks=checks,
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
        resolve_clone_url=_clone_url(git_repository),
        provider_factory=lambda _snapshot: ScriptedProvider(
            payloads={"correctness": {"findings": []}}
        ),
    )
    report = await worker.execute_claimed_attempt(lease.attempt_id)
    assert report is not None
    assert report.attempt_id == lease.attempt_id
    assert worker.pipeline_invocations == 1
    assert checks.updated == [CheckRunStatus.IN_PROGRESS]
    result_json = await github_store.get_review_result(lease.attempt_id)
    assert result_json is not None
    assert "worktree-review.cli.result/v1" in result_json
    events = await github_store.list_review_events(lease.attempt_id)
    assert events[0].event_type == "attempt.created"
    assert events[0].surface == "github"
    assert any(event.event_type.startswith("stage.") for event in events)
    assert events[-1].event_type == "attempt.completed"

    superseded = await state.start_authoritative_attempt(
        change_request=locator, request_key=request_key
    )
    skipped = await worker.execute_claimed_attempt(lease.attempt_id)
    assert skipped is None
    assert worker.pipeline_invocations == 1
    assert superseded.attempt_id != lease.attempt_id


@pytest.mark.asyncio
async def test_worker_refuses_drifted_policy(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    oid = head_oid(git_repository)
    _, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    _, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    state = InMemoryAuthoritativeAttemptStore()
    github_store = InMemoryGitHubReviewStore()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = _request_key(oid, review_version)
    lease = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    drifted = AttemptExecutionSnapshot(
        attempt_id=lease.attempt_id,
        change_request=locator,
        request_key=request_key,
        proposed_ref="HEAD",
        review_policy_semver=review_version.semver,
        review_policy_sha256="f" * 64,
        compute_policy_semver=compute_version.semver,
        compute_policy_sha256=compute_version.sha256,
    )
    await github_store.save_execution_snapshot(drifted)
    worker = GitHubReviewWorker(
        state=state,
        github_store=github_store,
        mirrors=RepositoryMirrorManager(tmp_path / "mirrors"),
        checks=_FakeChecks(),
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
        resolve_clone_url=_clone_url(git_repository),
        provider_factory=lambda _snapshot: ScriptedProvider(
            payloads={"correctness": {"findings": []}}
        ),
    )
    with pytest.raises(PolicyDriftError):
        await worker.execute_claimed_attempt(lease.attempt_id)
    assert worker.pipeline_invocations == 0


def _clone_url(repository: Path):
    async def _resolve(_snapshot: AttemptExecutionSnapshot) -> str:
        return str(repository)

    return _resolve


@pytest.mark.asyncio
async def test_worker_executes_from_frozen_policy_documents_after_file_changes(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    """Frozen documents let an old Attempt resume even after policy files change."""
    import yaml

    from worktree_review.core.policy import policy_version_identity

    oid = head_oid(git_repository)
    _, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    _, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    review_document = yaml.safe_load((policy_dir / "review-policy.yaml").read_text())
    compute_document = yaml.safe_load((policy_dir / "compute-policy.yaml").read_text())
    state = InMemoryAuthoritativeAttemptStore()
    github_store = InMemoryGitHubReviewStore()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = _request_key(oid, review_version)
    lease = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    await github_store.save_execution_snapshot(
        AttemptExecutionSnapshot(
            attempt_id=lease.attempt_id,
            change_request=locator,
            request_key=request_key,
            proposed_ref="HEAD",
            review_policy_semver=review_version.semver,
            review_policy_sha256=review_version.sha256,
            compute_policy_semver=compute_version.semver,
            compute_policy_sha256=compute_version.sha256,
            review_policy_document=review_document,
            compute_policy_document=compute_document,
        )
    )
    # Newer Attempts legitimately adopt new policy content; the old Attempt
    # must not see it.
    (policy_dir / "review-policy.yaml").write_text(
        (policy_dir / "review-policy.yaml").read_text().replace("  - major\n", ""),
        encoding="utf-8",
    )
    worker = GitHubReviewWorker(
        state=state,
        github_store=github_store,
        mirrors=RepositoryMirrorManager(tmp_path / "mirrors"),
        checks=_FakeChecks(),
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
        resolve_clone_url=_clone_url(git_repository),
        provider_factory=lambda _snapshot: ScriptedProvider(
            payloads={"correctness": {"findings": []}}
        ),
    )
    report = await worker.execute_claimed_attempt(lease.attempt_id)
    assert report is not None
    assert report.review_policy_version.sha256 == review_version.sha256
    del policy_version_identity


@pytest.mark.asyncio
async def test_worker_rejects_tampered_frozen_documents(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    import yaml

    oid = head_oid(git_repository)
    _, review_version = load_review_policy(policy_dir / "review-policy.yaml")
    _, compute_version = load_compute_policy(policy_dir / "compute-policy.yaml")
    review_document = yaml.safe_load((policy_dir / "review-policy.yaml").read_text())
    compute_document = yaml.safe_load((policy_dir / "compute-policy.yaml").read_text())
    state = InMemoryAuthoritativeAttemptStore()
    github_store = InMemoryGitHubReviewStore()
    locator = GitHubChangeRequestLocator(
        installation_id=7, repository="octo/example", pull_request_number=42
    )
    request_key = _request_key(oid, review_version)
    lease = await state.start_authoritative_attempt(change_request=locator, request_key=request_key)
    review_document["blocking_severities"] = ["critical"]  # tampered: weakens the gate
    await github_store.save_execution_snapshot(
        AttemptExecutionSnapshot(
            attempt_id=lease.attempt_id,
            change_request=locator,
            request_key=request_key,
            proposed_ref="HEAD",
            review_policy_semver=review_version.semver,
            review_policy_sha256=review_version.sha256,
            compute_policy_semver=compute_version.semver,
            compute_policy_sha256=compute_version.sha256,
            review_policy_document=review_document,
            compute_policy_document=compute_document,
        )
    )
    worker = GitHubReviewWorker(
        state=state,
        github_store=github_store,
        mirrors=RepositoryMirrorManager(tmp_path / "mirrors"),
        checks=_FakeChecks(),
        review_policy_path=policy_dir / "review-policy.yaml",
        compute_policy_path=policy_dir / "compute-policy.yaml",
        resolve_clone_url=_clone_url(git_repository),
        provider_factory=lambda _snapshot: ScriptedProvider(
            payloads={"correctness": {"findings": []}}
        ),
    )
    with pytest.raises(PolicyDriftError, match="snapshot identity"):
        await worker.execute_claimed_attempt(lease.attempt_id)
    assert worker.pipeline_invocations == 0
