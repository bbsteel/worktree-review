"""Small user-facing provider configuration built into trusted CLI policy."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal, cast

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from worktree_review.core.errors import PolicyValidationError
from worktree_review.core.identity import PolicyVersionIdentity
from worktree_review.core.policy import (
    COMPUTE_POLICY_DOCUMENT_ID,
    ComputePolicy,
    ProviderName,
    policy_version_identity,
)
from worktree_review.schemas import USER_CONFIG_SCHEMA_ID, load_schema

USER_CONFIG_DOCUMENT_ID: Literal["worktree-review.config/v1"] = "worktree-review.config/v1"
DEFAULT_USER_CONFIG_VERSION = "0.1.0"
DEFAULT_USER_MAX_OUTPUT_TOKENS_PER_CALL = 4096
DEFAULT_KNOWN_RETENTION = "Provider-defined; review this provider account's retention terms."
DEFAULT_REMOTE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
}
DEFAULT_REMOTE_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}
_ENVIRONMENT_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class ProviderConfiguration(BaseModel):
    """Resolved provider connection data; secrets never enter Compute Policy identity."""

    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    url: str | None = None
    api_key: SecretStr | None = None
    command: tuple[str, ...] = ()


class UserConfiguration(BaseModel):
    """Minimal CLI provider configuration; advanced compute belongs in Compute Policy."""

    model_config = ConfigDict(extra="forbid")

    schema_name: Literal["worktree-review.config/v1"] = Field(
        alias="schema",
        default=USER_CONFIG_DOCUMENT_ID,
    )
    version: str = DEFAULT_USER_CONFIG_VERSION
    provider: Literal["anthropic", "openai", "local-cli"]
    url: str | None = Field(default=None, min_length=1)
    key: str | None = Field(default=None, min_length=1)
    command: tuple[str, ...] | None = None
    model: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_provider_shape(self) -> UserConfiguration:
        if self.provider in ("anthropic", "openai"):
            if self.key is None:
                raise ValueError("key is required for a remote provider")
            if self.command is not None:
                raise ValueError("command is only valid for provider local-cli")
        else:
            if self.command is None or not self.command:
                raise ValueError("command is required for provider local-cli")
            if any(not argument for argument in self.command):
                raise ValueError("command arguments must not be empty")
            if self.url is not None or self.key is not None:
                raise ValueError("url and key are only valid for a remote provider")
        return self


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyValidationError(f"cannot read user configuration {path}: {exc}") from exc
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PolicyValidationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PolicyValidationError(f"user configuration {path} must be a YAML mapping")
    return cast(dict[str, Any], loaded)


def _validate_against_schema(document: dict[str, Any], path: Path) -> None:
    schema = load_schema(USER_CONFIG_SCHEMA_ID)
    try:
        jsonschema.validate(instance=document, schema=schema)
    except jsonschema.ValidationError as exc:
        raise PolicyValidationError(
            f"user configuration {path} failed schema {USER_CONFIG_SCHEMA_ID}: {exc.message}"
        ) from exc


def _resolve_api_key(raw_key: str, path: Path) -> str:
    environment_match = _ENVIRONMENT_REFERENCE.fullmatch(raw_key.strip())
    if environment_match is None:
        return raw_key
    environment_name = environment_match.group(1)
    resolved_key = os.environ.get(environment_name, "").strip()
    if not resolved_key:
        raise PolicyValidationError(
            f"user configuration {path} references {environment_name}, but that environment "
            "variable is not set"
        )
    return resolved_key


def _resolved_remote_url(configuration: UserConfiguration) -> str:
    if configuration.provider == "local-cli":
        raise PolicyValidationError("local-cli configuration has no remote URL")
    return configuration.url or DEFAULT_REMOTE_URLS[configuration.provider]


def _compute_policy_document(configuration: UserConfiguration) -> dict[str, object]:
    if configuration.provider == "local-cli":
        command = configuration.command
        if command is None:
            raise PolicyValidationError("local-cli configuration has no command")
        model = configuration.model or command[0]
        destination = "local CLI command"
        permit_remote_transmission = False
    else:
        model = configuration.model or DEFAULT_REMOTE_MODELS[configuration.provider]
        destination = _resolved_remote_url(configuration)
        permit_remote_transmission = True

    document: dict[str, object] = {
        "schema": COMPUTE_POLICY_DOCUMENT_ID,
        "version": configuration.version,
        "provider": configuration.provider,
        "model": model,
        "max_output_tokens_per_call": DEFAULT_USER_MAX_OUTPUT_TOKENS_PER_CALL,
        "permit_remote_transmission": permit_remote_transmission,
        "data_destination": destination,
        "known_retention": DEFAULT_KNOWN_RETENTION,
    }
    return document


def load_user_configuration(
    path: Path,
) -> tuple[ComputePolicy, PolicyVersionIdentity, ProviderConfiguration]:
    """Load the minimal user config and derive the trusted Compute Policy."""

    document = _load_yaml_mapping(path)
    _validate_against_schema(document, path)
    try:
        configuration = UserConfiguration.model_validate(document)
    except Exception as exc:
        raise PolicyValidationError(f"user configuration {path} is invalid: {exc}") from exc

    compute_document = _compute_policy_document(configuration)
    try:
        compute_policy = ComputePolicy.model_validate(compute_document)
    except Exception as exc:
        raise PolicyValidationError(
            f"derived Compute Policy from user configuration {path} is invalid: {exc}"
        ) from exc

    if configuration.provider == "local-cli":
        provider_configuration = ProviderConfiguration(
            provider="local-cli",
            command=configuration.command or (),
        )
    else:
        if configuration.key is None:
            raise PolicyValidationError("remote provider configuration requires key")
        provider_configuration = ProviderConfiguration(
            provider=configuration.provider,
            url=_resolved_remote_url(configuration),
            api_key=SecretStr(_resolve_api_key(configuration.key, path)),
        )
    return (
        compute_policy,
        policy_version_identity(compute_document, configuration.version),
        provider_configuration,
    )
