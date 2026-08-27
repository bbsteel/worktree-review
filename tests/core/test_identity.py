from __future__ import annotations

import pytest
from pydantic import ValidationError

from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ReviewIdentity,
)


def _candidate(*, merge_tree_oid: str = "c" * 40) -> MergeCandidateIdentity:
    return MergeCandidateIdentity(
        source_repository="/repo",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        merge_tree_oid=merge_tree_oid,
    )


def _policy(*, semver: str = "1.0.0") -> PolicyVersionIdentity:
    return PolicyVersionIdentity(semver=semver, sha256="d" * 64)


def test_review_identity_fields_are_only_candidate_and_policy_version() -> None:
    assert tuple(ReviewIdentity.model_fields) == ("candidate", "review_policy_version")


def test_review_identity_rejects_platform_change_request_id() -> None:
    with pytest.raises(ValidationError, match="platform_change_request_id"):
        ReviewIdentity.model_validate(
            {
                "candidate": _candidate().model_dump(),
                "review_policy_version": _policy().model_dump(),
                "platform_change_request_id": "github:pr:42",
            }
        )


def test_review_identity_equality_depends_only_on_candidate_and_policy_version() -> None:
    identity = ReviewIdentity(candidate=_candidate(), review_policy_version=_policy())
    assert ReviewIdentity(candidate=_candidate(), review_policy_version=_policy()) == identity
    assert (
        ReviewIdentity(
            candidate=_candidate(merge_tree_oid="e" * 40),
            review_policy_version=_policy(),
        )
        != identity
    )
    assert (
        ReviewIdentity(
            candidate=_candidate(),
            review_policy_version=_policy(semver="1.0.1"),
        )
        != identity
    )
