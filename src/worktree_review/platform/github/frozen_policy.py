"""Single trusted path for frozen Review Policy resolution (P3 §5.1.4).

Detail projection, Finding ``blocking``, Bypass capability, Bypass POST, and
Check-facing policy consumers must share this conclusion. A parse failure,
identity drift, or unprovable legacy snapshot never silently becomes
``None`` with a hardcoded Critical/Major fallback.
"""

from __future__ import annotations

from pathlib import Path

from worktree_review.core.identity import PolicyVersionIdentity
from worktree_review.core.policy import (
    ReviewPolicy,
    load_review_policy,
    policy_version_identity,
)
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot


class FrozenReviewPolicyError(RuntimeError):
    """The frozen Review Policy cannot be trusted for authorization decisions."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def resolve_frozen_review_policy(
    snapshot: AttemptExecutionSnapshot,
    *,
    legacy_review_policy_path: Path | None = None,
    expected_report_version: PolicyVersionIdentity | None = None,
) -> ReviewPolicy:
    """Return the Review Policy that produced the standing decision.

    Prefer the immutable ``review_policy_document`` embedded in the execution
    snapshot and require its canonical SHA-256 to match the snapshot identity.
    Legacy snapshots without a frozen document may fall back to a trusted file
    path only when that path is supplied and the on-disk identity still matches
    the snapshot; anything else fails closed.
    """

    if snapshot.review_policy_document is not None:
        try:
            review_policy = ReviewPolicy.model_validate(snapshot.review_policy_document)
            frozen_version = policy_version_identity(
                snapshot.review_policy_document, review_policy.version
            )
        except Exception as exc:
            raise FrozenReviewPolicyError(
                "bypass_policy_changed",
                "the frozen Review Policy document is invalid",
            ) from exc
        if frozen_version.sha256 != snapshot.review_policy_sha256:
            raise FrozenReviewPolicyError(
                "bypass_policy_changed",
                "the frozen Review Policy document does not match its identity",
            )
    else:
        if legacy_review_policy_path is None:
            raise FrozenReviewPolicyError(
                "bypass_policy_changed",
                "the Attempt has no frozen Review Policy document and no trusted legacy path",
            )
        try:
            review_policy, frozen_version = load_review_policy(legacy_review_policy_path)
        except Exception as exc:
            raise FrozenReviewPolicyError(
                "bypass_policy_changed",
                "the trusted Review Policy is unavailable for the legacy snapshot",
            ) from exc
        if frozen_version.sha256 != snapshot.review_policy_sha256:
            raise FrozenReviewPolicyError(
                "bypass_policy_changed",
                "the trusted Review Policy drifted from the frozen snapshot",
            )

    if expected_report_version is not None and frozen_version != expected_report_version:
        raise FrozenReviewPolicyError(
            "bypass_policy_changed",
            "the standing decision was produced under a different Review Policy",
        )
    return review_policy
