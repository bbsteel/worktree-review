"""Inline and file-level GitHub comments. No finding is silently dropped (D13)."""

from worktree_review.core.errors import UnimplementedStageError
from worktree_review.core.report import ReviewReport


async def publish_finding_comments(report: ReviewReport) -> None:
    raise UnimplementedStageError("GitHub finding comments are not implemented")
