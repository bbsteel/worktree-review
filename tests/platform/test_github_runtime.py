from __future__ import annotations

import httpx
import pytest

from worktree_review.platform.github.runtime import (
    GitHubPullRequestResolver,
    GitHubRestClient,
)
from worktree_review.server.state import GitHubChangeRequestLocator


class _StaticGitHubApi:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.paths: list[str] = []

    async def get_json(self, path: str) -> dict[str, object]:
        self.paths.append(path)
        return self.payload


@pytest.mark.asyncio
async def test_pull_request_resolver_uses_current_refs_and_external_policy(
    policy_dir,
) -> None:
    github_api = _StaticGitHubApi(
        {
            "base": {
                "ref": "main",
                "sha": "a" * 40,
                "repo": {"full_name": "octo/example"},
            },
            "head": {
                "sha": "b" * 40,
                "repo": {"full_name": "octo/example"},
            },
        }
    )
    resolver = GitHubPullRequestResolver(
        github_api=github_api,
        review_policy_path=policy_dir / "review-policy.yaml",
    )

    resolution = await resolver.resolve_current_request(
        GitHubChangeRequestLocator(
            installation_id=7,
            repository="octo/example",
            pull_request_number=42,
        )
    )

    assert github_api.paths == ["/repos/octo/example/pulls/42"]
    assert resolution.request_key.source_repository == "octo/example"
    assert resolution.request_key.target_ref == "main"
    assert resolution.request_key.target_head_oid == "a" * 40
    assert resolution.request_key.proposed_head_oid == "b" * 40


@pytest.mark.asyncio
async def test_github_rest_client_sends_bearer_token_and_maps_repository_role() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"permission": "write"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url="https://api.github.test",
    ) as http_client:
        github_api = GitHubRestClient(http_client=http_client, token="installation-token")
        role = await github_api.repository_role(
            installation_id=7,
            repository="octo/example",
            actor="maintainer",
        )

    assert role == "write"
    assert requests[0].url.path == "/repos/octo/example/collaborators/maintainer/permission"
    assert requests[0].headers["authorization"] == "Bearer installation-token"
