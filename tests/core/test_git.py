from __future__ import annotations

from pathlib import Path

import pytest

import worktree_review.core.git as git_module
from worktree_review.core.errors import GitRequiredError
from worktree_review.core.git import (
    MIN_GIT_VERSION,
    GitCliError,
    TreeEntry,
    _affected_baseline_paths,
    _git_working_tree_changed_paths,
    parse_git_version,
    require_git_version,
)


def test_parse_git_version_accepts_common_banners() -> None:
    assert parse_git_version("git version 2.50.1") == (2, 50, 1)
    assert parse_git_version("git version 2.43.0.windows.1") == (2, 43, 0)
    assert parse_git_version("git version 2.39.2 (Apple Git-143)") == (2, 39, 2)


def test_parse_git_version_rejects_garbage() -> None:
    with pytest.raises(GitRequiredError):
        parse_git_version("not a version")


@pytest.mark.asyncio
async def test_require_git_version_on_this_machine() -> None:
    version = await require_git_version()
    assert version >= MIN_GIT_VERSION


def test_affected_baseline_paths_uses_path_ancestors_without_cross_prefix_matches() -> None:
    baseline_entries = {
        path: TreeEntry(mode="100644", object_type="blob", object_id="a" * 40, path=path)
        for path in (
            "src/app.py",
            "src/generated/schema.py",
            "src-old/app.py",
            "docs/README.md",
        )
    }

    affected_paths = _affected_baseline_paths(
        baseline_entries,
        ("src", "docs"),
    )

    assert affected_paths == (
        "docs/README.md",
        "src/app.py",
        "src/generated/schema.py",
    )


@pytest.mark.asyncio
async def test_unmerged_paths_are_escaped_before_git_error_is_rendered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_git_nul_paths(*arguments: str, repository: Path) -> tuple[str, ...]:
        del arguments, repository
        return ("conflict\x1b]8;;https://attacker.invalid\x1b\\",)

    monkeypatch.setattr(git_module, "_git_nul_paths", fake_git_nul_paths)

    with pytest.raises(GitCliError) as raised_error:
        await _git_working_tree_changed_paths(tmp_path)

    error_message = str(raised_error.value)
    assert "\x1b" not in error_message
    assert r"\x1b" in error_message
