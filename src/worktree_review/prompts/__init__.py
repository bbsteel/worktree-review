"""Versioned, product-owned prompt layers used by review dimensions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

PROMPT_SET_VERSION = "0.1.0"

BUILTIN_DIMENSION_PROMPT_IDS: tuple[str, ...] = (
    "correctness",
    "security",
    "performance",
    "architecture",
    "maintainability",
    "style",
)

_PROMPT_ROOT = files("worktree_review.prompts")
_DIMENSION_PROMPT_FILES: dict[str, str] = {
    "correctness": "30-dimensions/correctness.md",
    "security": "30-dimensions/security.md",
    "performance": "30-dimensions/performance.md",
    "architecture": "30-dimensions/architecture.md",
    "maintainability": "30-dimensions/maintainability.md",
    "style": "30-dimensions/style.md",
}
_COMMON_PROMPT_RESOURCE_PATHS: tuple[str, ...] = (
    "00-product/role.md",
    "10-safety/untrusted-content.md",
    "20-review/evidence.md",
)
_OUTPUT_PROMPT_RESOURCE_PATH = "40-output/structured-findings.md"


@dataclass(frozen=True)
class PromptLayer:
    """One inspectable, product-owned layer in an effective dimension prompt."""

    sequence: int
    resource_path: str
    content: str


@cache
def _read_prompt_layer(relative_path: str) -> str:
    return _PROMPT_ROOT.joinpath(*relative_path.split("/")).read_text(encoding="utf-8").strip()


def prompt_layer_resource_paths(dimension_id: str) -> tuple[str, ...]:
    """Return the trusted resource order for one review dimension."""

    dimension_layer = _DIMENSION_PROMPT_FILES.get(dimension_id, "30-dimensions/default.md")
    return (*_COMMON_PROMPT_RESOURCE_PATHS, dimension_layer, _OUTPUT_PROMPT_RESOURCE_PATH)


@cache
def load_prompt_layers(dimension_id: str) -> tuple[PromptLayer, ...]:
    """Load the effective ordered prompt layers for user inspection and model calls."""

    return tuple(
        PromptLayer(
            sequence=sequence,
            resource_path=resource_path,
            content=_read_prompt_layer(resource_path),
        )
        for sequence, resource_path in enumerate(prompt_layer_resource_paths(dimension_id), start=1)
    )


def dimension_system_prompt(dimension_id: str) -> str:
    """Compose the ordered product, safety, review, dimension, and output layers."""

    rendered_layers = [
        f"Prompt layer {layer.sequence}:\n{layer.content}"
        for layer in load_prompt_layers(dimension_id)
    ]
    return f"Dimension: {dimension_id}\n" + "\n\n".join(rendered_layers)


__all__ = [
    "BUILTIN_DIMENSION_PROMPT_IDS",
    "PROMPT_SET_VERSION",
    "PromptLayer",
    "dimension_system_prompt",
    "load_prompt_layers",
    "prompt_layer_resource_paths",
]
