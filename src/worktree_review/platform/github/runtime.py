"""Concrete GitHub server dependencies for retry and Checks publication (D8, D13, D14).

The runtime adapter owns transport and deployment configuration. It resolves
only trusted GitHub API data and an externally stored Review Policy version;
none of those platform details are added to core identity models.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

import httpx

from worktree_review.core.identity import ReviewRequestKey
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.core.provider import ProviderClient, build_provider
from worktree_review.platform.github.authz import GitHubRoleRetryAuthorizer
from worktree_review.platform.github.checks import (
    DEFAULT_PUBLIC_BASE_URL,
    CheckRunPayload,
)
from worktree_review.platform.github.durable import DurableGitHubAttemptWorker
from worktree_review.platform.github.errors import GitHubApiError, ServerConfigurationError
from worktree_review.platform.github.mirrors import RepositoryMirrorManager
from worktree_review.platform.github.persistence import (
    GitHubReviewStore,
    PostgresGitHubReviewStore,
)
from worktree_review.platform.github.publication import GitHubCheckPublisher
from worktree_review.platform.github.retry import (
    GitHubRetryCoordinator,
    RetryResolution,
)
from worktree_review.platform.github.snapshot import AttemptExecutionSnapshot
from worktree_review.platform.github.triggers import GitHubTriggerCoordinator, QueuedAttemptPreparer
from worktree_review.platform.github.worker import (
    CloneUrlResolver,
    GitHubReviewWorker,
    ProviderFactory,
)
from worktree_review.server.state import (
    AttemptLease,
    GitHubChangeRequestLocator,
    PostgresAuthoritativeAttemptStore,
)

if TYPE_CHECKING:
    import asyncpg  # type: ignore[import-untyped]
    from pgqueuer import PgQueuer


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


class GitHubTokenProvider(Protocol):
    async def token_for_installation(self, installation_id: int) -> str:
        """Return a short-lived installation token. Never log the secret."""
        ...


class GitHubClientFactory:
    """Issue per-installation REST clients from the App token provider."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        token_provider: GitHubTokenProvider,
    ) -> None:
        self._http_client = http_client
        self._token_provider = token_provider

    async def rest_client(self, installation_id: int) -> GitHubRestClient:
        token = await self._token_provider.token_for_installation(installation_id)
        return GitHubRestClient(http_client=self._http_client, token=token)


class SnapshotBackedGitHubChecks:
    """Check transport that binds each payload to the Attempt's installation token."""

    def __init__(self, *, factory: GitHubClientFactory, github_store: GitHubReviewStore) -> None:
        self._factory = factory
        self._github_store = github_store

    async def _client_for_payload(self, payload: CheckRunPayload) -> GitHubRestClient:
        attempt_id = payload.external_id.removeprefix("worktree-review:")
        snapshot = await self._github_store.get_execution_snapshot(attempt_id)
        if snapshot is None:
            raise GitHubApiError(f"missing execution snapshot for {attempt_id}")
        return await self._factory.rest_client(snapshot.installation_id)

    async def create_check_run(self, *, repository: str, payload: CheckRunPayload) -> int:
        client = await self._client_for_payload(payload)
        return await client.create_check_run(repository=repository, payload=payload)

    async def update_check_run(
        self,
        *,
        repository: str,
        check_run_id: int,
        payload: CheckRunPayload,
    ) -> None:
        client = await self._client_for_payload(payload)
        await client.update_check_run(
            repository=repository, check_run_id=check_run_id, payload=payload
        )


class InstallationAwarePullRequestResolver:
    def __init__(self, *, factory: GitHubClientFactory, review_policy_path: Path) -> None:
        self._factory = factory
        self._review_policy_path = review_policy_path

    async def resolve_current_request(
        self,
        change_request: GitHubChangeRequestLocator,
    ) -> RetryResolution:
        client = await self._factory.rest_client(change_request.installation_id)
        return await GitHubPullRequestResolver(
            github_api=client,
            review_policy_path=self._review_policy_path,
        ).resolve_current_request(change_request)


class InstallationAwareRoleLookup:
    def __init__(self, factory: GitHubClientFactory) -> None:
        self._factory = factory

    async def repository_role(
        self,
        *,
        installation_id: int,
        repository: str,
        actor: str,
    ) -> str | None:
        client = await self._factory.rest_client(installation_id)
        return await client.repository_role(
            installation_id=installation_id,
            repository=repository,
            actor=actor,
        )


@dataclass
class ServerRuntime:
    """Resources initialized for one FastAPI process."""

    retry_coordinator: GitHubRetryCoordinator
    database_pool: asyncpg.Pool
    http_client: httpx.AsyncClient
    github_store: PostgresGitHubReviewStore | None = None
    trigger_coordinator: GitHubTriggerCoordinator | None = None
    attempt_store: PostgresAuthoritativeAttemptStore | None = None
    publisher: GitHubCheckPublisher | None = None
    review_worker: GitHubReviewWorker | None = None
    durable_worker: DurableGitHubAttemptWorker | None = None
    token_provider: GitHubTokenProvider | None = None
    worker_task: asyncio.Task[None] | None = field(default=None)
    _closed: bool = field(default=False, init=False, repr=False)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.worker_task is not None:
            self.worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker_task
            self.worker_task = None
        await self.http_client.aclose()
        await self.database_pool.close()


async def build_server_runtime(
    *,
    database_url: str,
    github_api_url: str,
    review_policy_path: Path,
    compute_policy_path: Path,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    mirror_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
    token_provider: GitHubTokenProvider | None = None,
    clone_url_resolver: CloneUrlResolver | None = None,
    provider_factory: ProviderFactory | None = None,
    github_token: str | None = None,
) -> ServerRuntime:
    """Initialize the production GitHub Gate dependency graph for FastAPI startup."""

    if not database_url:
        raise ServerConfigurationError("WORKTREE_REVIEW_DATABASE_URL is required")
    _require_trusted_policy_file(review_policy_path)
    _require_trusted_policy_file(compute_policy_path)
    try:
        load_review_policy(review_policy_path)
    except Exception as exc:
        raise ServerConfigurationError(
            f"trusted Review Policy cannot be loaded: {review_policy_path}"
        ) from exc
    try:
        load_compute_policy(compute_policy_path)
    except Exception as exc:
        raise ServerConfigurationError(
            f"trusted Compute Policy cannot be loaded: {compute_policy_path}"
        ) from exc

    import asyncpg
    from pgqueuer import PgQueuer

    from worktree_review.platform.github.tokens import load_github_token_provider

    owns_http_client = http_client is None
    database_pool = await asyncpg.create_pool(database_url)
    if http_client is None:
        http_client = httpx.AsyncClient(base_url=github_api_url.rstrip("/"), timeout=20.0)
    try:
        if token_provider is None:
            token_source = dict(os.environ if environ is None else environ)
            if github_token and "WORKTREE_REVIEW_GITHUB_TOKEN" not in token_source:
                token_source["WORKTREE_REVIEW_GITHUB_TOKEN"] = github_token
            token_provider = load_github_token_provider(token_source, http_client=http_client)
        state = PostgresAuthoritativeAttemptStore(database_pool)
        await state.initialise()
        github_store = PostgresGitHubReviewStore(database_pool)
        await github_store.initialise()
        queue = PgQueuer.from_asyncpg_pool(database_pool)
        if queue.queries is None:
            raise ServerConfigurationError("pgqueuer query repository is not initialized")
        await queue.queries.install()
        factory = GitHubClientFactory(http_client=http_client, token_provider=token_provider)
        checks = SnapshotBackedGitHubChecks(factory=factory, github_store=github_store)
        enqueuer = PgQueuerAttemptEnqueuer(queue)
        public_base = public_base_url.rstrip("/") or DEFAULT_PUBLIC_BASE_URL
        retry_coordinator = GitHubRetryCoordinator(
            state=state,
            authorizer=GitHubRoleRetryAuthorizer(InstallationAwareRoleLookup(factory)),
            resolver=InstallationAwarePullRequestResolver(
                factory=factory,
                review_policy_path=review_policy_path,
            ),
            enqueue_attempt=enqueuer,
            prepare_queued_attempt=QueuedAttemptPreparer(
                github_store=github_store,
                checks=checks,
                review_policy_path=review_policy_path,
                compute_policy_path=compute_policy_path,
                public_base_url=public_base,
            ),
        )
        trigger_coordinator = GitHubTriggerCoordinator(
            state=state,
            github_store=github_store,
            checks=checks,
            enqueue_attempt=enqueuer,
            review_policy_path=review_policy_path,
            compute_policy_path=compute_policy_path,
            public_base_url=public_base,
        )
        publisher = GitHubCheckPublisher(
            state=state,
            github_store=github_store,
            checks=checks,
            public_base_url=public_base,
        )
        resolved_clone = clone_url_resolver or _github_clone_url_resolver(factory)
        resolved_provider = provider_factory or _trusted_provider_factory(compute_policy_path)
        mirrors = RepositoryMirrorManager(
            mirror_root if mirror_root is not None else _default_mirror_root()
        )
        review_worker = GitHubReviewWorker(
            state=state,
            github_store=github_store,
            mirrors=mirrors,
            checks=checks,
            review_policy_path=review_policy_path,
            compute_policy_path=compute_policy_path,
            resolve_clone_url=resolved_clone,
            provider_factory=resolved_provider,
            public_base_url=public_base,
        )
        durable_worker = DurableGitHubAttemptWorker(
            github_store=github_store,
            review_worker=review_worker,
            publisher=publisher,
        )
        return ServerRuntime(
            retry_coordinator=retry_coordinator,
            database_pool=database_pool,
            http_client=http_client,
            github_store=github_store,
            trigger_coordinator=trigger_coordinator,
            attempt_store=state,
            publisher=publisher,
            review_worker=review_worker,
            durable_worker=durable_worker,
            token_provider=token_provider,
        )
    except Exception:
        if owns_http_client:
            await http_client.aclose()
        await database_pool.close()
        raise


def _github_clone_url_resolver(factory: GitHubClientFactory) -> CloneUrlResolver:
    async def resolve(snapshot: AttemptExecutionSnapshot) -> str:
        client = await factory.rest_client(snapshot.installation_id)
        payload = await client.get_json(
            f"/repos/{quote(snapshot.change_request.repository, safe='/')}"
        )
        clone_url = payload.get("clone_url")
        if not isinstance(clone_url, str) or not clone_url:
            raise GitHubApiError("GitHub repository response is missing clone_url")
        return clone_url

    return resolve


def _trusted_provider_factory(compute_policy_path: Path) -> ProviderFactory:
    def factory(_snapshot: AttemptExecutionSnapshot) -> ProviderClient:
        compute_policy, _version = load_compute_policy(compute_policy_path)
        return build_provider(compute_policy)

    return factory


def _default_mirror_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "worktree-review" / "mirrors"
    return Path.home() / ".local" / "state" / "worktree-review" / "mirrors"


ServerRuntimeBuilder = Callable[[], Awaitable[ServerRuntime]]


def _require_trusted_policy_file(review_policy_path: Path) -> None:
    if not review_policy_path.is_file():
        raise ServerConfigurationError(
            f"trusted Review Policy file does not exist: {review_policy_path}"
        )


def _expand_user_path(path_value: str) -> Path:
    return Path(path_value).expanduser()


async def build_server_runtime_from_environment() -> ServerRuntime:
    """Build the GitHub Gate runtime from deployment configuration."""

    review_policy_path_value = os.environ.get("WORKTREE_REVIEW_REVIEW_POLICY_PATH")
    if not review_policy_path_value:
        raise ServerConfigurationError("WORKTREE_REVIEW_REVIEW_POLICY_PATH is required")
    compute_policy_path_value = os.environ.get("WORKTREE_REVIEW_COMPUTE_POLICY_PATH")
    if not compute_policy_path_value:
        raise ServerConfigurationError("WORKTREE_REVIEW_COMPUTE_POLICY_PATH is required")
    mirror_root_value = os.environ.get("WORKTREE_REVIEW_MIRROR_ROOT")
    return await build_server_runtime(
        database_url=os.environ.get("WORKTREE_REVIEW_DATABASE_URL", ""),
        github_api_url=os.environ.get(
            "WORKTREE_REVIEW_GITHUB_API_URL",
            "https://api.github.com",
        ),
        review_policy_path=_expand_user_path(review_policy_path_value),
        compute_policy_path=_expand_user_path(compute_policy_path_value),
        public_base_url=os.environ.get(
            "WORKTREE_REVIEW_PUBLIC_BASE_URL",
            DEFAULT_PUBLIC_BASE_URL,
        ),
        mirror_root=None if not mirror_root_value else _expand_user_path(mirror_root_value),
    )
