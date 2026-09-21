"""Frozen Provider Profile snapshots for Web Attempts.

At Attempt creation the referenced Provider Profile's non-secret identity
(provider, endpoint, local CLI argv/adapter, credential *reference*) is
frozen into the run row. Historical Attempts therefore never change when a
profile is later edited or deleted, and the worker — server-side only —
resolves the credential reference into a ProviderConfiguration at execution
time. Secret values never enter the snapshot, events, or API responses.
"""

from __future__ import annotations

import json
from typing import Any, cast, get_args

from pydantic import SecretStr

from worktree_review.core.config import (
    DEFAULT_LOCAL_DATA_DESTINATION,
    DEFAULT_LOCAL_KNOWN_RETENTION,
    DEFAULT_REMOTE_URLS,
    LocalCliAdapterName,
    ProviderConfiguration,
    local_cli_configuration_fingerprint,
)
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.policy import ComputePolicy, ProviderName
from worktree_review.platform.web.registry import (
    profile_command_argv,
    resolve_credential_reference,
)

FROZEN_PROVIDER_SCHEMA = "worktree-review.frozen-provider/v1"

_LOCAL_CLI_ADAPTERS = frozenset(get_args(LocalCliAdapterName))


def freeze_provider_profile(profile_row: dict[str, Any]) -> str:
    """Serialize the profile's non-secret configuration identity for one Attempt."""

    document = {
        "schema": FROZEN_PROVIDER_SCHEMA,
        "profile_id": str(profile_row.get("id") or ""),
        "profile_name": str(profile_row.get("name") or ""),
        "provider": str(profile_row.get("provider") or ""),
        "endpoint": profile_row.get("endpoint"),
        "local_cli_adapter": profile_row.get("local_cli_adapter"),
        "local_cli_command": list(profile_command_argv(profile_row)),
        "adapter_label": profile_row.get("adapter_label"),
        "credential_reference": profile_row.get("credential_reference"),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def parse_frozen_provider_snapshot(frozen_json: str) -> dict[str, Any]:
    loaded = json.loads(frozen_json)
    if not isinstance(loaded, dict) or loaded.get("schema") != FROZEN_PROVIDER_SCHEMA:
        raise InvalidInvocationError("frozen provider snapshot has an unknown schema")
    return loaded


def resolve_frozen_provider_configuration(
    frozen_provider_json: str | None,
    *,
    compute_policy: ComputePolicy,
) -> ProviderConfiguration | None:
    """Resolve the frozen snapshot into a ProviderConfiguration (server-side only).

    Returns None only for legacy rows created before profile binding existed;
    those fall back to the environment-based defaults inside build_provider.
    """

    if frozen_provider_json is None:
        return None
    snapshot = parse_frozen_provider_snapshot(frozen_provider_json)
    provider = str(snapshot.get("provider") or "")
    if provider != compute_policy.provider:
        raise InvalidInvocationError(
            "frozen provider profile does not match the Compute Policy provider"
        )
    if provider == "local-cli":
        command = profile_command_argv(snapshot)
        if not command:
            raise InvalidInvocationError("frozen local-cli profile has no command argv")
        adapter = str(snapshot.get("local_cli_adapter") or "worktree-json")
        if adapter not in _LOCAL_CLI_ADAPTERS:
            raise InvalidInvocationError(f"unknown local-cli adapter: {adapter}")
        adapter_name = cast(LocalCliAdapterName, adapter)
        expected_fingerprint = local_cli_configuration_fingerprint(
            command=command,
            adapter=adapter_name,
            model=compute_policy.model,
            data_destination=compute_policy.data_destination,
            known_retention=compute_policy.known_retention,
        )
        if compute_policy.provider_configuration_fingerprint != expected_fingerprint:
            raise InvalidInvocationError(
                "frozen local-cli configuration does not match the Compute Policy "
                "provider_configuration_fingerprint"
            )
        return ProviderConfiguration(
            provider="local-cli",
            command=command,
            adapter=adapter_name,
            data_destination=compute_policy.data_destination or DEFAULT_LOCAL_DATA_DESTINATION,
            known_retention=compute_policy.known_retention or DEFAULT_LOCAL_KNOWN_RETENTION,
            configuration_fingerprint=expected_fingerprint,
        )
    endpoint = snapshot.get("endpoint")
    url = (
        str(endpoint)
        if isinstance(endpoint, str) and endpoint
        else DEFAULT_REMOTE_URLS.get(provider)
    )
    if url is None:
        raise InvalidInvocationError(f"no default endpoint for provider {provider!r}")
    reference = snapshot.get("credential_reference")
    if not isinstance(reference, str) or not reference:
        raise InvalidInvocationError("frozen remote provider profile has no credential reference")
    resolved_key = resolve_credential_reference(reference)
    return ProviderConfiguration(
        provider=cast(ProviderName, provider),
        url=url,
        api_key=SecretStr(resolved_key),
    )
