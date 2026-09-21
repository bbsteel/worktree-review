from __future__ import annotations

import json

import httpx
import pytest

from worktree_review.platform.github.checks import (
    CheckRunConclusion,
    CheckRunOutput,
    CheckRunPayload,
    CheckRunStatus,
)
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
        return httpx.Response(200, json={"permission": "write", "role_name": "write"})

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_role"),
    [
        ({"permission": "admin", "role_name": "admin"}, "admin"),
        ({"permission": "write", "role_name": "maintain"}, "maintain"),
        ({"permission": "write", "role_name": "write"}, "write"),
        ({"permission": "triage", "role_name": "triage"}, "triage"),
        ({"permission": "read", "role_name": "read"}, "read"),
        # Custom roles often report permission=write; role_name must win and fail closed.
        ({"permission": "write", "role_name": "release-manager"}, None),
        ({"permission": "admin", "role_name": "org-custom"}, None),
        ({"permission": "write"}, None),
        ({"role_name": "not-a-base-role"}, None),
        ({}, None),
    ],
)
async def test_github_rest_client_repository_role_prefers_role_name_and_fails_closed(
    payload: dict[str, str],
    expected_role: str | None,
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url="https://api.github.test",
    ) as http_client:
        github_api = GitHubRestClient(http_client=http_client, token="installation-token")
        role = await github_api.repository_role(
            installation_id=7,
            repository="octo/example",
            actor="contributor",
        )

    assert role == expected_role


@pytest.mark.asyncio
async def test_github_rest_client_publishes_and_updates_check_runs() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": 321})
        return httpx.Response(200, json={"id": 321})

    payload = CheckRunPayload(
        head_sha="c" * 40,
        status=CheckRunStatus.COMPLETED,
        conclusion=CheckRunConclusion.SUCCESS,
        external_id="worktree-review:attempt-123",
        output=CheckRunOutput(
            title="Worktree Review: Passed",
            summary="passed",
            text="details",
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url="https://api.github.test",
    ) as http_client:
        github_api = GitHubRestClient(http_client=http_client, token="installation-token")
        check_run_id = await github_api.create_check_run(
            repository="octo/example",
            payload=payload,
        )
        await github_api.update_check_run(
            repository="octo/example",
            check_run_id=check_run_id,
            payload=payload,
        )

    assert check_run_id == 321
    assert [request.method for request in requests] == ["POST", "PATCH"]
    assert requests[0].url.path == "/repos/octo/example/check-runs"
    assert requests[1].url.path == "/repos/octo/example/check-runs/321"
    assert requests[0].headers["authorization"] == "Bearer installation-token"
    request_payload = json.loads(requests[0].content)
    assert request_payload["external_id"] == "worktree-review:attempt-123"
