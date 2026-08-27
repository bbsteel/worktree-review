"""Live repository-role verification for bypass. Never trust comment text (D9, PRD §16)."""

from worktree_review.core.errors import UnimplementedStageError


async def actor_may_bypass(*, installation_id: int, repository: str, actor: str) -> bool:
    raise UnimplementedStageError("GitHub bypass authorization is not implemented")
