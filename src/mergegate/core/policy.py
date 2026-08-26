"""Review Policy and Compute Policy load, validate, and version identity (D5)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergegate.core.errors import PolicyValidationError
from mergegate.core.findings import (
    DEFAULT_BLOCKING_SEVERITIES,
    DEFAULT_MINIMUM_BLOCKING_EVIDENCE_BAND,
    EvidenceBand,
    Severity,
)
from mergegate.core.identity import PolicyVersionIdentity
from mergegate.schemas import (
    COMPUTE_POLICY_SCHEMA_ID,
    REVIEW_POLICY_SCHEMA_ID,
    load_schema,
)

REVIEW_POLICY_DOCUMENT_ID: Literal["mergegate.review-policy/v1"] = "mergegate.review-policy/v1"
COMPUTE_POLICY_DOCUMENT_ID: Literal["mergegate.compute-policy/v1"] = "mergegate.compute-policy/v1"

ProviderName = Literal["anthropic", "openai"]

DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_OPTIONAL_CONTEXT_GLOBS: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md")


class ContextPolicy(BaseModel):
    """How Review Policy classifies workspace and changed-file context (PRD §10)."""

    model_config = ConfigDict(frozen=True)

    max_file_bytes: Annotated[int, Field(ge=1)] = DEFAULT_MAX_FILE_BYTES
    excluded_globs: tuple[str, ...] = ()
    mandatory_globs: tuple[str, ...] = ()
    optional_globs: tuple[str, ...] = DEFAULT_OPTIONAL_CONTEXT_GLOBS


class ReviewPolicy(BaseModel):
    """Trusted Review Policy. Never loaded from the repository under review."""

    model_config = ConfigDict(frozen=True)

    schema_name: Literal["mergegate.review-policy/v1"] = Field(
        alias="schema",
        default=REVIEW_POLICY_DOCUMENT_ID,
    )
    version: str
    required_dimensions: tuple[str, ...] = Field(min_length=1)
    blocking_severities: tuple[Severity, ...] = DEFAULT_BLOCKING_SEVERITIES
    minimum_blocking_evidence_band: EvidenceBand = DEFAULT_MINIMUM_BLOCKING_EVIDENCE_BAND
    context: ContextPolicy = Field(default_factory=ContextPolicy)

    @field_validator("blocking_severities")
    @classmethod
    def _blocking_severities_unique(cls, value: tuple[Severity, ...]) -> tuple[Severity, ...]:
        if len(set(value)) != len(value):
            raise ValueError("blocking_severities must not contain duplicates")
        return value


class ComputePolicy(BaseModel):
    """Trusted Compute Policy. Changes do not invalidate standing decisions."""

    model_config = ConfigDict(frozen=True)

    schema_name: Literal["mergegate.compute-policy/v1"] = Field(
        alias="schema",
        default=COMPUTE_POLICY_DOCUMENT_ID,
    )
    version: str
    provider: ProviderName
    model: str
    max_budget_usd: Annotated[Decimal, Field(ge=0)]
    allow_start_under_uncertain_price: bool = False
    data_destination: str
    known_retention: str


def canonical_policy_bytes(document: dict[str, Any]) -> bytes:
    """Canonical JSON of the parsed policy mapping; hashing never uses raw YAML."""

    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def policy_version_identity(document: dict[str, Any], semver: str) -> PolicyVersionIdentity:
    digest = hashlib.sha256(canonical_policy_bytes(document)).hexdigest()
    return PolicyVersionIdentity(semver=semver, sha256=digest)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyValidationError(f"cannot read policy file {path}: {exc}") from exc
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PolicyValidationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PolicyValidationError(f"policy {path} must be a YAML mapping")
    return cast(dict[str, Any], loaded)


def _validate_against_schema(document: dict[str, Any], schema_id: str, path: Path) -> None:
    schema = load_schema(schema_id)
    try:
        jsonschema.validate(instance=document, schema=schema)
    except jsonschema.ValidationError as exc:
        raise PolicyValidationError(
            f"policy {path} failed schema {schema_id}: {exc.message}"
        ) from exc


def load_review_policy(path: Path) -> tuple[ReviewPolicy, PolicyVersionIdentity]:
    document = _load_yaml_mapping(path)
    _validate_against_schema(document, REVIEW_POLICY_SCHEMA_ID, path)
    try:
        policy = ReviewPolicy.model_validate(document)
    except Exception as exc:
        raise PolicyValidationError(f"policy {path} is invalid: {exc}") from exc
    return policy, policy_version_identity(document, policy.version)


def load_compute_policy(path: Path) -> tuple[ComputePolicy, PolicyVersionIdentity]:
    document = _load_yaml_mapping(path)
    _validate_against_schema(document, COMPUTE_POLICY_SCHEMA_ID, path)
    try:
        policy = ComputePolicy.model_validate(document)
    except Exception as exc:
        raise PolicyValidationError(f"policy {path} is invalid: {exc}") from exc
    return policy, policy_version_identity(document, policy.version)
