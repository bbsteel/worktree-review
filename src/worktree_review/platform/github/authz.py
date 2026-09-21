"""Live repository-role verification for retry and bypass.

Comment or webhook text is never trusted for authorization (D9, PRD §16).
"""

from typing import Protocol

from worktree_review.server.state import GitHubChangeRequestLocator

# GitHub's collaborator permission API returns both ``permission`` (legacy
# coarse value) and ``role_name`` (base or custom role). Only these base roles
# are ever trusted; custom role names fail closed even when permission=write.
STANDARD_REPOSITORY_ROLES = frozenset({"admin", "maintain", "write", "triage", "read"})
RETRY_ALLOWED_REPOSITORY_ROLES = frozenset({"admin", "maintain", "write"})
# PRD §16: bypass authorization defaults to write/maintain/admin; a stricter
# allowlist may only come from trusted deployment/Policy configuration.
BYPASS_ALLOWED_REPOSITORY_ROLES = frozenset({"admin", "maintain", "write"})


def normalize_standard_repository_role(
    *,
    role_name: object,
    permission: object,
) -> str | None:
    """Return a known base repository role, preferring ``role_name``.

    Custom, missing, or inconsistent GitHub role payloads yield ``None`` so
    callers fail closed instead of treating ``permission=write`` as Bypass
    authority (P3 design §4.2 / GitHub collaborator permission API).
    """

    if isinstance(role_name, str) and role_name:
        if role_name in STANDARD_REPOSITORY_ROLES:
            return role_name
        return None
    # Without a trusted role_name the legacy permission field is never enough:
    # GitHub maps maintain→write there and custom roles often report write.
    del permission
    return None


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


class GitHubRoleBypassAuthorizer:
    """Live role lookup for bypass authorization; webhook or comment text never suffices."""

    def __init__(self, role_lookup: GitHubRepositoryRoleLookup) -> None:
        self._role_lookup = role_lookup

    async def may_bypass(
        self,
        *,
        change_request: GitHubChangeRequestLocator,
        actor_login: str,
    ) -> bool:
        role = await self._role_lookup.repository_role(
            installation_id=change_request.installation_id,
            repository=change_request.repository,
            actor=actor_login,
        )
        return role in BYPASS_ALLOWED_REPOSITORY_ROLES
