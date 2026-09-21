from __future__ import annotations

import pytest

from worktree_review.platform.github.authz import (
    GitHubRoleRetryAuthorizer,
    normalize_standard_repository_role,
)
from worktree_review.server.state import GitHubChangeRequestLocator


@pytest.mark.parametrize(
    ("role_name", "permission", "expected"),
    [
        ("admin", "admin", "admin"),
        ("maintain", "write", "maintain"),
        ("write", "write", "write"),
        ("triage", "triage", "triage"),
        ("read", "read", "read"),
        ("release-manager", "write", None),
        ("org-custom", "admin", None),
        (None, "write", None),
        ("", "admin", None),
        ("write", None, "write"),
    ],
)
def test_normalize_standard_repository_role_prefers_role_name(
    role_name: str | None,
    permission: str | None,
    expected: str | None,
) -> None:
    assert (
        normalize_standard_repository_role(role_name=role_name, permission=permission) == expected
    )


class _StaticRepositoryRoleLookup:
    def __init__(self, role: str | None) -> None:
        self.role = role
        self.calls: list[tuple[int, str, str]] = []

    async def repository_role(
        self,
        *,
        installation_id: int,
        repository: str,
        actor: str,
    ) -> str | None:
        self.calls.append((installation_id, repository, actor))
        return self.role


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_role", ["admin", "maintain", "write"])
async def test_retry_authorization_requires_an_allowed_live_repository_role(
    repository_role: str,
) -> None:
    role_lookup = _StaticRepositoryRoleLookup(repository_role)
    authorizer = GitHubRoleRetryAuthorizer(role_lookup)
    change_request = GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )

    assert await authorizer.may_retry(change_request=change_request, actor="maintainer") is True
    assert role_lookup.calls == [(7, "octo/example", "maintainer")]


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_role", [None, "read", "triage", "invalid"])
async def test_retry_authorization_rejects_non_maintainer_live_roles(
    repository_role: str | None,
) -> None:
    role_lookup = _StaticRepositoryRoleLookup(repository_role)
    authorizer = GitHubRoleRetryAuthorizer(role_lookup)
    change_request = GitHubChangeRequestLocator(
        installation_id=7,
        repository="octo/example",
        pull_request_number=42,
    )

    assert await authorizer.may_retry(change_request=change_request, actor="contributor") is False
