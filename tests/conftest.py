from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REVIEW_POLICY_YAML = """\
schema: worktree-review.review-policy/v1
version: 0.1.0
required_dimensions:
  - correctness
blocking_severities:
  - critical
  - major
minimum_blocking_evidence_band: supported
"""

COMPUTE_POLICY_YAML = """\
schema: worktree-review.compute-policy/v1
version: 0.1.0
provider: anthropic
model: claude-sonnet-4-5
max_budget_usd: 1
allow_start_under_uncertain_price: false
permit_remote_transmission: true
input_usd_per_million_tokens: 3
output_usd_per_million_tokens: 15
data_destination: https://api.anthropic.com
known_retention: none-in-skeleton
"""


def _git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "worktree-review-test@example.com")
    _git(repo, "config", "user.name", "Worktree Review Test")
    (repo / "README").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture(autouse=True)
def isolate_web_state_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKTREE_REVIEW_WEB_DATABASE", str(tmp_path / "web.sqlite"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))


@pytest.fixture
def policy_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "trusted-policy"
    directory.mkdir()
    (directory / "review-policy.yaml").write_text(REVIEW_POLICY_YAML, encoding="utf-8")
    (directory / "compute-policy.yaml").write_text(COMPUTE_POLICY_YAML, encoding="utf-8")
    return directory
