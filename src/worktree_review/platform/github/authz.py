"""Live repository-role verification for bypass. Never trust comment text (D9, PRD §16)."""

from typing import Protocol

from worktree_review.core.errors import UnimplementedStageError
from worktree_review.server.state import GitHubChangeRequestLocator

RETRY_ALLOWED_REPOSITORY_ROLES = frozenset({"admin", "maintain", "write"})


class GitHubRepositoryRoleLookup(Protocol):
    async def repository_role(
        self,
        *,
        installation_id: int,
        repository: str,
        actor: str,
    ) -> str | None:
        """Return the live GitHub repository role for an actor."""
        ...


class GitHubRoleRetryAuthorizer:
    """Use a live role lookup for D14; never infer authorization from webhook text."""

    def __init__(self, role_lookup: GitHubRepositoryRoleLookup) -> None:
        self._role_lookup = role_lookup

    async def may_retry(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        actor: str,
    ) -> bool:
        role = await self._role_lookup.repository_role(
            installation_id=change_request.installation_id,
            repository=change_request.repository,
            actor=actor,
        )
        return role in RETRY_ALLOWED_REPOSITORY_ROLES


async def actor_may_bypass(*, installation_id: int, repository: str, actor: str) -> bool:
    raise UnimplementedStageError("GitHub bypass authorization is not implemented")
