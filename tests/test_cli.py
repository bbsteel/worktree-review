from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema
from typer.testing import CliRunner

from mergegate.cli import app
from mergegate.platform.cli.exit_codes import CliExitCode
from mergegate.platform.cli.result import cli_result_schema

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "review" in result.stdout


def test_missing_target_flag_is_invalid_invocation() -> None:
    completed = subprocess.run(
        ["mergegate", "review"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == int(CliExitCode.INVALID_INVOCATION)


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.0.1"


def test_review_json_is_error_and_matches_schema(git_repository: Path, policy_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--target",
            "main",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == int(CliExitCode.ERROR)
    document = json.loads(result.stdout)
    jsonschema.validate(instance=document, schema=cli_result_schema())
    assert document["gate_state"] == "Error"
    assert document["merge_tree_oid"] is not None
    assert len(document["merge_tree_oid"]) >= 40
    assert document["target_ref"] == "main"
    assert len(document["target_head_oid"]) == 40
    stages = {item["stage"]: item["status"] for item in document["stage_outcomes"]}
    assert stages["construct-merge"] == "completed"
    assert stages["prepare-workspace"] == "completed"
    assert stages["gather-context"] == "completed"
    assert stages["run-dimensions"] == "failed"
    assert document["coverage"]["required_coverage_complete"] is True


def test_dirty_worktree_is_invalid_invocation(git_repository: Path, policy_dir: Path) -> None:
    (git_repository / "dirty").write_text("nope\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "review",
            "--target",
            "main",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
    assert "dirty" in result.stderr.lower()


def test_policy_inside_worktree_is_invalid_invocation(
    git_repository: Path, policy_dir: Path
) -> None:
    inside = git_repository / "review-policy.yaml"
    inside.write_text((policy_dir / "review-policy.yaml").read_text(encoding="utf-8"))
    subprocess.run(
        ["git", "add", "review-policy.yaml"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add in-repo policy"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    result = runner.invoke(
        app,
        [
            "review",
            "--target",
            "main",
            "--repository",
            str(git_repository),
            "--policy",
            str(inside),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
    assert "inside the reviewed worktree" in result.stderr


def test_missing_target_ref_is_invalid_invocation(git_repository: Path, policy_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--target",
            "does-not-exist",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
