from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.core.context import ContextClass, ContextItem, GatheredContext
from worktree_review.core.dimension import (
    dimension_system_prompt,
    findings_from_payload,
    run_required_dimensions,
)
from worktree_review.core.errors import ProviderError
from worktree_review.core.findings import EvidenceSource
from worktree_review.core.policy import ComputePolicy, ReviewPolicy
from worktree_review.core.provider import ScriptedProvider
from worktree_review.core.report import CoverageRecord, StageStatus
from worktree_review.core.review_worktree import ReviewWorktree
from worktree_review.prompts import load_prompt_layers, prompt_layer_resource_paths


def _policy() -> ReviewPolicy:
    return ReviewPolicy.model_validate(
        {
            "schema": "worktree-review.review-policy/v1",
            "version": "1.0.0",
            "required_dimensions": ["correctness", "security"],
        }
    )


def _context() -> GatheredContext:
    return GatheredContext(
        coverage=CoverageRecord(required_coverage_complete=True, reviewed=("a.py",)),
        items=(
            ContextItem(
                path="a.py",
                context_class=ContextClass.MANDATORY,
                body="print(1)\n",
            ),
        ),
    )


def _compute_policy() -> ComputePolicy:
    return ComputePolicy.model_validate(
        {
            "schema": "worktree-review.compute-policy/v1",
            "version": "1.0.0",
            "provider": "anthropic",
            "model": "scripted",
            "max_budget_usd": 1,
            "input_usd_per_million_tokens": 3,
            "output_usd_per_million_tokens": 15,
            "data_destination": "https://api.anthropic.com",
            "known_retention": "test",
        }
    )


def _review_worktree(tmp_path: Path) -> ReviewWorktree:
    tree = tmp_path / "tree"
    tree.mkdir()
    return ReviewWorktree(
        root=tree,
        container_root=tmp_path,
        merge_tree_oid="a" * 40,
        owner_note="test",
    )


def test_findings_from_payload_fingerprints() -> None:
    findings = findings_from_payload(
        {
            "findings": [
                {
                    "path": "a.py",
                    "start_line": 1,
                    "end_line": 1,
                    "quoted_text": "print(1)",
                    "severity": "major",
                    "evidence_band": "supported",
                    "problem_statement": "wrong",
                    "expected_impact": "break",
                    "repair_guidance": None,
                }
            ]
        },
        dimension_id="correctness",
    )
    assert len(findings) == 1
    assert findings[0].dimension_id == "correctness"
    assert findings[0].fingerprint


def test_dimension_prompt_is_composed_from_visible_ordered_layers() -> None:
    prompt = dimension_system_prompt("security")

    assert prompt.index("Prompt layer 1:") < prompt.index("Prompt layer 2:")
    assert prompt.index("Prompt layer 2:") < prompt.index("Prompt layer 3:")
    assert prompt.index("Prompt layer 3:") < prompt.index("Prompt layer 4:")
    assert prompt.index("Prompt layer 4:") < prompt.index("Prompt layer 5:")
    assert "authorization, injection, secret exposure" in prompt
    assert "Use the structured findings schema only" in prompt


def test_prompt_layers_expose_effective_resource_order() -> None:
    layers = load_prompt_layers("security")

    assert tuple(layer.sequence for layer in layers) == (1, 2, 3, 4, 5)
    assert tuple(layer.resource_path for layer in layers) == prompt_layer_resource_paths("security")
    assert layers[0].resource_path == "00-product/role.md"
    assert layers[3].resource_path == "30-dimensions/security.md"
    assert layers[-1].resource_path == "40-output/structured-findings.md"


def test_inverted_line_range_is_rejected() -> None:
    with pytest.raises(ProviderError, match="inverted"):
        findings_from_payload(
            {
                "findings": [
                    {
                        "path": "a.py",
                        "start_line": 4,
                        "end_line": 1,
                        "quoted_text": "x",
                        "severity": "minor",
                        "evidence_band": "insufficient",
                        "problem_statement": "x",
                        "expected_impact": "x",
                        "repair_guidance": None,
                    }
                ]
            },
            dimension_id="correctness",
        )


@pytest.mark.asyncio
async def test_required_dimensions_run_concurrently_and_keep_partial_results(
    tmp_path: Path,
) -> None:
    provider = ScriptedProvider(
        payloads={
            "correctness": {
                "findings": [
                    {
                        "path": "a.py",
                        "start_line": 1,
                        "end_line": 1,
                        "quoted_text": "print(1)",
                        "severity": "major",
                        "evidence_band": "supported",
                        "problem_statement": "bug",
                        "expected_impact": "fail",
                        "repair_guidance": None,
                    }
                ]
            }
            # security missing → that dimension fails
        }
    )
    results = await run_required_dimensions(
        _review_worktree(tmp_path), _context(), _policy(), provider, _compute_policy()
    )
    by_id = {item.outcome.dimension_id: item for item in results}
    assert by_id["correctness"].outcome.status is StageStatus.COMPLETED
    assert by_id["security"].outcome.status is StageStatus.FAILED
    assert len(by_id["correctness"].findings) == 1
    correctness_span = by_id["correctness"].findings[0].evidence_spans[0]
    assert correctness_span.source is EvidenceSource.REVIEW_WORKTREE
    assert correctness_span.snapshot_identity == "a" * 40
    assert set(provider.dimension_ids_called) == {"correctness", "security"}
