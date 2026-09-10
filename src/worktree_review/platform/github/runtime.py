"""Concrete GitHub server dependencies for retry and Checks publication (D8, D13, D14).

The runtime adapter owns transport and deployment configuration. It resolves
only trusted GitHub API data and an externally stored Review Policy version;
none of those platform details are added to core identity models.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

import httpx

from worktree_review.core.identity import ReviewRequestKey
from worktree_review.core.policy import load_review_policy
from worktree_review.platform.github.authz import (
    GitHubRepositoryRoleLookup,
    GitHubRoleRetryAuthorizer,
)
from worktree_review.platform.github.checks import CheckRunPayload
from worktree_review.platform.github.persistence import PostgresGitHubReviewStore
from worktree_review.platform.github.retry import (
    GitHubRetryCoordinator,
    RetryResolution,
)
from worktree_review.server.state import (
    AttemptLease,
    GitHubChangeRequestLocator,
    PostgresAuthoritativeAttemptStore,
)

if TYPE_CHECKING:
    import asyncpg  # type: ignore[import-untyped]
    from pgqueuer import PgQueuer


class ServerConfigurationError(RuntimeError):
    """Required production server configuration is absent or invalid."""


class GitHubApiError(RuntimeError):
    """The trusted GitHub API could not resolve a retry input."""


class GitHubApiTransport(Protocol):
    async def get_json(self, path: str) -> dict[str, object]:
        """Fetch one GitHub API object."""
        ...


class GitHubRestClient:
    """Minimal authenticated GitHub REST client for retry and Checks adapters."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        token: str,
    ) -> None:
        self._http_client = http_client
        self._token = token

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_json(self, path: str) -> dict[str, object]:
        response = await self._http_client.get(
            path,
            headers=self._headers(),
        )
        return _decode_github_json_response(response)

    async def _send_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = await self._http_client.request(
            method,
            path,
            headers=self._headers(),
            json=payload,
        )
        return _decode_github_json_response(response)

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        response_payload = await self._send_json(
            "POST",
            f"/repos/{quote(repository, safe='/')}/check-runs",
            payload.as_github_payload(),
        )
        check_run_id = response_payload.get("id")
        if isinstance(check_run_id, bool) or not isinstance(check_run_id, int) or check_run_id <= 0:
            raise GitHubApiError("GitHub check-run response is missing a positive numeric id")
        return check_run_id

    async def update_check_run(
        self,
        *,
        repository: str,
        check_run_id: int,
        payload: CheckRunPayload,
    ) -> None:
        await self._send_json(
            "PATCH",
            f"/repos/{quote(repository, safe='/')}/check-runs/{check_run_id}",
            payload.as_github_payload(),
        )

    async def repository_role(
        self,
        *,
        installation_id: int,
        repository: str,
        actor: str,
    ) -> str | None:
        del installation_id
        payload = await self.get_json(
            f"/repos/{quote(repository, safe='/')}/collaborators/{quote(actor, safe='')}/permission"
        )
        permission = payload.get("permission")
        return permission if isinstance(permission, str) else None


def _decode_github_json_response(response: httpx.Response) -> dict[str, object]:
    if response.is_error:
        raise GitHubApiError(f"GitHub API request failed with HTTP {response.status_code}")
    try:
        decoded_payload = response.json()
    except ValueError as exc:
        raise GitHubApiError("GitHub API returned invalid JSON") from exc
    if not isinstance(decoded_payload, dict):
        raise GitHubApiError("GitHub API response must be a JSON object")
    return decoded_payload


def _nested_object(payload: dict[str, object], field_name: str) -> dict[str, object]:
    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise GitHubApiError(f"GitHub API response is missing object field {field_name}")
    return value


def _required_string(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise GitHubApiError(f"GitHub API response is missing string field {field_name}")
    return value


class GitHubPullRequestResolver:
    """Resolve current PR refs and the trusted server-side Review Policy."""

    def __init__(
        self,
        *,
        github_api: GitHubApiTransport,
        review_policy_path: Path,
    ) -> None:
        self._github_api = github_api
        self._review_policy_path = review_policy_path

    async def resolve_current_request(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> RetryResolution:
        payload = await self._github_api.get_json(
            f"/repos/{quote(change_request.repository, safe='/')}/pulls/"
            f"{change_request.pull_request_number}"
        )
        base = _nested_object(payload, "base")
        head = _nested_object(payload, "head")
        base_repository = _required_string(_nested_object(base, "repo"), "full_name")
        head_repository = _required_string(_nested_object(head, "repo"), "full_name")
        if base_repository != change_request.repository:
            raise GitHubApiError(
                "GitHub pull request base repository does not match the webhook locator"
            )
        if head_repository != base_repository:
            raise GitHubApiError(
                "cross-repository pull requests are outside the first-stage GitHub scope"
            )
        _, review_policy_version = load_review_policy(self._review_policy_path)
        return RetryResolution(
            request_key=ReviewRequestKey(
                source_repository=head_repository,
                target_ref=_required_string(base, "ref"),
                target_head_oid=_required_string(base, "sha"),
                proposed_head_oid=_required_string(head, "sha"),
                review_policy_version=review_policy_version,
            )
        )


class AttemptEnqueueClient(Protocol):
    async def enqueue(
        self,
        entrypoint: str,
        payload: bytes,
        *,
        dedupe_key: str,
    ) -> None:
        """Publish an attempt-keyed job to the durable queue."""
        ...


class PgQueuerAttemptEnqueuer:
    """Map an authoritative Attempt to a pgqueuer job keyed by Attempt ID."""

    def __init__(self, queue: PgQueuer, *, entrypoint: str = "worktree-review.attempt") -> None:
        self._queue = queue
        self._entrypoint = entrypoint

    async def __call__(self, attempt: AttemptLease) -> None:
        queries = self._queue.queries
        if queries is None:
            raise RuntimeError("pgqueuer query repository is not initialized")
        await queries.enqueue(
            self._entrypoint,
            attempt.model_dump_json().encode("utf-8"),
            dedupe_key=attempt.attempt_id,
            on_conflict="skip",
        )


@dataclass
class ServerRuntime:
    """Resources initialized for one FastAPI process."""

    retry_coordinator: GitHubRetryCoordinator
    database_pool: asyncpg.Pool
    http_client: httpx.AsyncClient
    github_store: PostgresGitHubReviewStore | None = None

    async def aclose(self) -> None:
        await self.http_client.aclose()
        await self.database_pool.close()


async def build_server_runtime(
    *,
    database_url: str,
    github_token: str,
    github_api_url: str,
    review_policy_path: Path,
) -> ServerRuntime:
    """Initialize the production retry dependency graph for FastAPI startup."""

    if not database_url:
        raise ServerConfigurationError("WORKTREE_REVIEW_DATABASE_URL is required")
    if not github_token:
        raise ServerConfigurationError("WORKTREE_REVIEW_GITHUB_TOKEN is required")
    _require_trusted_policy_file(review_policy_path)
    try:
        load_review_policy(review_policy_path)
    except Exception as exc:
        raise ServerConfigurationError(
            f"trusted Review Policy cannot be loaded: {review_policy_path}"
        ) from exc

    import asyncpg
    from pgqueuer import PgQueuer

    database_pool = await asyncpg.create_pool(database_url)
    http_client = httpx.AsyncClient(base_url=github_api_url.rstrip("/"), timeout=20.0)
    try:
        state = PostgresAuthoritativeAttemptStore(database_pool)
        await state.initialise()
        github_store = PostgresGitHubReviewStore(database_pool)
        await github_store.initialise()
        queue = PgQueuer.from_asyncpg_pool(database_pool)
        if queue.queries is None:
            raise ServerConfigurationError("pgqueuer query repository is not initialized")
        await queue.queries.install()
        github_api = GitHubRestClient(http_client=http_client, token=github_token)
        retry_coordinator = GitHubRetryCoordinator(
            state=state,
            authorizer=GitHubRoleRetryAuthorizer(_repository_role_lookup(github_api)),
            resolver=GitHubPullRequestResolver(
                github_api=github_api,
                review_policy_path=review_policy_path,
            ),
            enqueue_attempt=PgQueuerAttemptEnqueuer(queue),
        )
        return ServerRuntime(
            retry_coordinator=retry_coordinator,
            database_pool=database_pool,
            http_client=http_client,
            github_store=github_store,
        )
    except Exception:
        await http_client.aclose()
        await database_pool.close()
        raise


def _repository_role_lookup(github_api: GitHubRestClient) -> GitHubRepositoryRoleLookup:
    return github_api


ServerRuntimeBuilder = Callable[[], Awaitable[ServerRuntime]]


def _require_trusted_policy_file(review_policy_path: Path) -> None:
    if not review_policy_path.is_file():
        raise ServerConfigurationError(
            f"trusted Review Policy file does not exist: {review_policy_path}"
        )


def _expand_user_path(path_value: str) -> Path:
    return Path(path_value).expanduser()


async def build_server_runtime_from_environment() -> ServerRuntime:
    """Build the retry runtime from deployment configuration."""

    review_policy_path_value = os.environ.get("WORKTREE_REVIEW_REVIEW_POLICY_PATH")
    if not review_policy_path_value:
        raise ServerConfigurationError("WORKTREE_REVIEW_REVIEW_POLICY_PATH is required")
    return await build_server_runtime(
        database_url=os.environ.get("WORKTREE_REVIEW_DATABASE_URL", ""),
        github_token=os.environ.get("WORKTREE_REVIEW_GITHUB_TOKEN", ""),
        github_api_url=os.environ.get(
            "WORKTREE_REVIEW_GITHUB_API_URL",
            "https://api.github.com",
        ),
        review_policy_path=_expand_user_path(review_policy_path_value),
    )
