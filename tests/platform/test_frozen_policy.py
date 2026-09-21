"""Shared frozen Review Policy trust path (P3 §5.1.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from worktree_review.core.identity import PolicyVersionIdentity, ReviewRequestKey
from worktree_review.core.policy import (
    ReviewPolicy,
    load_review_policy,
    policy_version_identity,
)
from worktree_review.platform.github.frozen_policy import (
    FrozenReviewPolicyError,
    resolve_frozen_review_policy,
)
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.server.state import GitHubChangeRequestLocator

_LOCATOR = GitHubChangeRequestLocator(
    installation_id=7, repository="octo/example", pull_request_number=42
)


def _minimal_review_policy_document(*, version: str = "1.0.0") -> dict[str, object]:
    return {
        "schema": "worktree-review.review-policy/v1",
        "version": version,
        "required_dimensions": ["correctness"],
        "blocking_severities": ["critical", "major"],
        "minimum_blocking_evidence_band": "supported",
        "context": {
            "max_file_bytes": 1048576,
            "excluded_globs": [],
            "mandatory_globs": [],
            "optional_globs": [],
        },
    }


def _snapshot_for(
    document: dict[str, object] | None,
    *,
    sha256: str,
    semver: str = "1.0.0",
) -> AttemptExecutionSnapshot:
    request_key = ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        review_policy_version=PolicyVersionIdentity(semver=semver, sha256=sha256),
    )
    return AttemptExecutionSnapshot(
        attempt_id="11111111-2222-3333-4444-555555555555",
        change_request=_LOCATOR,
        request_key=request_key,
        proposed_ref="feature",
        review_policy_semver=semver,
        review_policy_sha256=sha256,
        compute_policy_semver="1.0.0",
        compute_policy_sha256="e" * 64,
        review_policy_document=document,
    )


def test_resolve_frozen_review_policy_accepts_matching_document() -> None:
    document = _minimal_review_policy_document()
    policy = ReviewPolicy.model_validate(document)
    identity = policy_version_identity(document, policy.version)
    resolved = resolve_frozen_review_policy(_snapshot_for(document, sha256=identity.sha256))
    assert resolved.version == policy.version
    assert resolved.blocking_severities == policy.blocking_severities


def test_resolve_frozen_review_policy_rejects_sha_tamper() -> None:
    document = _minimal_review_policy_document()
    with pytest.raises(FrozenReviewPolicyError) as exc:
        resolve_frozen_review_policy(_snapshot_for(document, sha256="0" * 64))
    assert exc.value.code == "bypass_policy_changed"


def test_resolve_frozen_review_policy_rejects_invalid_schema() -> None:
    document = {"schema": "review-policy.v1", "version": "1.0.0"}
    with pytest.raises(FrozenReviewPolicyError) as exc:
        resolve_frozen_review_policy(_snapshot_for(document, sha256="a" * 64))
    assert exc.value.code == "bypass_policy_changed"


def test_legacy_fallback_requires_matching_trusted_file(tmp_path: Path) -> None:
    document = _minimal_review_policy_document()
    policy_path = tmp_path / "review-policy.yaml"
    policy_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    policy, identity = load_review_policy(policy_path)
    snapshot = _snapshot_for(None, sha256=identity.sha256, semver=policy.version)
    resolved = resolve_frozen_review_policy(snapshot, legacy_review_policy_path=policy_path)
    assert resolved.version == policy.version


def test_legacy_fallback_rejects_disk_drift(tmp_path: Path) -> None:
    original = _minimal_review_policy_document(version="1.0.0")
    drifted = _minimal_review_policy_document(version="1.0.1")
    policy_path = tmp_path / "review-policy.yaml"
    policy_path.write_text(yaml.safe_dump(drifted), encoding="utf-8")
    original_identity = policy_version_identity(
        original, ReviewPolicy.model_validate(original).version
    )
    snapshot = _snapshot_for(None, sha256=original_identity.sha256)
    with pytest.raises(FrozenReviewPolicyError) as exc:
        resolve_frozen_review_policy(snapshot, legacy_review_policy_path=policy_path)
    assert exc.value.code == "bypass_policy_changed"


def test_legacy_without_path_fails_closed() -> None:
    with pytest.raises(FrozenReviewPolicyError) as exc:
        resolve_frozen_review_policy(_snapshot_for(None, sha256="d" * 64))
    assert exc.value.code == "bypass_policy_changed"
