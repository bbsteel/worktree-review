"""Versioned JSON Schema documents. These are the source of truth for policy and results."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Final, cast

REVIEW_POLICY_SCHEMA_ID: Final = "review-policy.v1"
COMPUTE_POLICY_SCHEMA_ID: Final = "compute-policy.v1"
CLI_RESULT_SCHEMA_ID: Final = "cli-result.v1"
DIMENSION_FINDINGS_SCHEMA_ID: Final = "dimension-findings.v1"

_SCHEMA_FILES: Final[dict[str, str]] = {
    REVIEW_POLICY_SCHEMA_ID: "review-policy.v1.json",
    COMPUTE_POLICY_SCHEMA_ID: "compute-policy.v1.json",
    CLI_RESULT_SCHEMA_ID: "cli-result.v1.json",
    DIMENSION_FINDINGS_SCHEMA_ID: "dimension-findings.v1.json",
}


def load_schema(schema_id: str) -> dict[str, Any]:
    filename = _SCHEMA_FILES.get(schema_id)
    if filename is None:
        raise KeyError(f"unknown schema id: {schema_id}")
    payload = files("mergegate.schemas").joinpath(filename).read_text(encoding="utf-8")
    loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        raise TypeError(f"schema {schema_id} is not a JSON object")
    return cast(dict[str, Any], loaded)
