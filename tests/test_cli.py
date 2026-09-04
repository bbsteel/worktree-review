from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from tests.gitutil import commit_files, head_oid
from worktree_review.cli import app
from worktree_review.platform.cli.exit_codes import CliExitCode
from worktree_review.platform.cli.result import cli_result_schema

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "review" in result.stdout


def test_missing_target_defaults_to_current_worktree(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "review",
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
    assert document["target_ref"] == "HEAD"
    assert document["proposed_ref"] == "WORKTREE"
    assert document["proposed_source"] == "current-worktree-snapshot"
    assert document["target_head_oid"] == document["proposed_head_oid"]


def test_module_entrypoint_preserves_invalid_invocation_exit_code() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "worktree_review",
            "review",
            "--repository",
            "/tmp",
            "--policy",
            "/tmp/no-review.yaml",
            "--compute-policy",
            "/tmp/no-compute.yaml",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == int(CliExitCode.INVALID_INVOCATION)


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.0.1"


def test_review_json_is_error_and_matches_schema(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    assert document["proposed_ref"] == "WORKTREE"
    assert document["proposed_source"] == "current-worktree-snapshot"
    assert document["proposed_head_oid"] == document["target_head_oid"]
    assert len(document["target_head_oid"]) == 40
    stages = {item["stage"]: item["status"] for item in document["stage_outcomes"]}
    assert stages["construct-merge"] == "completed"
    assert stages["prepare-review-worktree"] == "completed"
    assert stages["gather-context"] == "completed"
    assert stages["run-dimensions"] == "failed"
    dimensions = {item["dimension_id"]: item for item in document["dimension_outcomes"]}
    assert dimensions["correctness"]["status"] == "not-started"
    assert document["coverage"]["required_coverage_complete"] is True
    assert document["attempt_id"]
    assert document["request_key"]["target_ref"] == "main"
    assert document["compute_policy_disclosure"] == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "data_destination": "https://api.anthropic.com",
        "known_retention": "none-in-skeleton",
    }
    assert "usage" in document
    assert "data_destination" in result.stderr
    assert "claude-sonnet-4-5" in result.stderr


def test_review_text_reports_error_context_and_dimension_status(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "review",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )

    assert result.exit_code == int(CliExitCode.ERROR)
    assert "Gate: Error" in result.stdout
    assert "Request key:" in result.stdout
    assert "Review identity: merge_tree=" in result.stdout
    assert "Provider/model: anthropic/claude-sonnet-4-5" in result.stdout
    assert "Dimensions:" in result.stdout
    assert "correctness: not-started" in result.stdout
    assert "Findings: 0" in result.stdout
    assert "Error:" in result.stdout


def test_remote_transmission_requires_compute_policy_permit(
    git_repository: Path, policy_dir: Path
) -> None:
    compute_path = policy_dir / "no-transmit.yaml"
    compute_path.write_text(
        (policy_dir / "compute-policy.yaml")
        .read_text(encoding="utf-8")
        .replace(
            "permit_remote_transmission: true",
            "permit_remote_transmission: false",
        ),
        encoding="utf-8",
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
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(compute_path),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
    assert "permit remote transmission" in result.stderr


def test_dirty_worktree_is_reviewed_as_snapshot(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "README").write_text("staged\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    (git_repository / "README").write_text("working\n", encoding="utf-8")
    (git_repository / "dirty").write_text("nope\n", encoding="utf-8")
    (git_repository / "new.py").write_text("print('new')\n", encoding="utf-8")
    original_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    assert document["proposed_ref"] == "WORKTREE"
    assert document["proposed_source"] == "current-worktree-snapshot"
    assert document["proposed_head_oid"] != document["target_head_oid"]
    snapshot_commit = document["proposed_head_oid"]
    for relative_path, expected_content in {
        "README": "working\n",
        "dirty": "nope\n",
        "new.py": "print('new')\n",
    }.items():
        snapshot_content = subprocess.run(
            ["git", "show", f"{snapshot_commit}:{relative_path}"],
            cwd=git_repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert snapshot_content == expected_content
    current_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert current_status == original_status
    staged_content = subprocess.run(
        ["git", "show", ":README"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert staged_content == "staged\n"


@pytest.mark.parametrize("hidden_index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_worktree_snapshot_includes_files_hidden_by_index_flags(
    git_repository: Path,
    policy_dir: Path,
    hidden_index_flag: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(
        ["git", "update-index", hidden_index_flag, "--", "README"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    (git_repository / "README").write_text(
        f"visible despite {hidden_index_flag}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "review",
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
    snapshot_content = subprocess.run(
        ["git", "show", f"{document['proposed_head_oid']}:README"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert snapshot_content == f"visible despite {hidden_index_flag}\n"


def test_worktree_snapshot_preserves_missing_skip_worktree_files(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hidden_path = git_repository / "sparse-only.py"
    hidden_path.write_text("must remain in the tree\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "sparse-only.py"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add sparse-only file"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "update-index", "--skip-worktree", "--", "sparse-only.py"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    hidden_path.unlink()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "review",
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
    assert document["proposed_head_oid"] == document["target_head_oid"]
    snapshot_content = subprocess.run(
        ["git", "show", f"{document['proposed_head_oid']}:sparse-only.py"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert snapshot_content == "must remain in the tree\n"


def test_worktree_snapshot_preserves_deletions_modes_symlinks_and_ignores(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit_files(
        git_repository,
        {
            ".gitignore": "ignored\n",
            "deleted.py": "delete me\n",
            "replaced/original.py": "directory entry\n",
            "script.py": "print('script')\n",
        },
        "snapshot baseline",
    )
    (git_repository / "deleted.py").unlink()
    (git_repository / "replaced/original.py").unlink()
    (git_repository / "replaced").rmdir()
    (git_repository / "replaced").write_text("regular entry\n", encoding="utf-8")
    (git_repository / "script.py").chmod(0o755)
    (git_repository / "link").symlink_to("README")
    (git_repository / "ignored").write_text("must not be reviewed\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "review",
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
    snapshot_commit = document["proposed_head_oid"]
    deleted_result = subprocess.run(
        ["git", "cat-file", "-e", f"{snapshot_commit}:deleted.py"],
        cwd=git_repository,
        check=False,
        capture_output=True,
    )
    ignored_result = subprocess.run(
        ["git", "cat-file", "-e", f"{snapshot_commit}:ignored"],
        cwd=git_repository,
        check=False,
        capture_output=True,
    )
    assert deleted_result.returncode != 0
    assert ignored_result.returncode != 0
    replaced_content = subprocess.run(
        ["git", "show", f"{snapshot_commit}:replaced"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert replaced_content == "regular entry\n"
    script_tree = subprocess.run(
        ["git", "ls-tree", snapshot_commit, "script.py"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert script_tree.startswith("100755 blob ")
    link_tree = subprocess.run(
        ["git", "ls-tree", snapshot_commit, "link"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert link_tree.startswith("120000 blob ")
    link_content = subprocess.run(
        ["git", "show", f"{snapshot_commit}:link"],
        cwd=git_repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert link_content == "README"


def test_nested_git_repository_is_an_unrepresentable_worktree_snapshot(
    git_repository: Path, policy_dir: Path
) -> None:
    nested_repository = git_repository / "nested"
    nested_repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(nested_repository)],
        check=True,
        capture_output=True,
    )
    (nested_repository / "file.py").write_text("nested\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "review",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
    assert "nested Git repositories" in result.stderr


def test_recent_commits_and_current_worktree_are_reviewed_together(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_commit_oid = head_oid(git_repository)
    commit_files(git_repository, {"first.py": "one\n"}, "first")
    second_commit_oid = commit_files(git_repository, {"second.py": "two\n"}, "second")
    (git_repository / "current.py").write_text("three\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "review",
            "--commits",
            "2",
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
    assert document["target_ref"] == "HEAD~2"
    assert document["target_head_oid"] == base_commit_oid
    assert document["proposed_ref"] == "WORKTREE"
    assert document["proposed_source"] == "current-worktree-snapshot"
    assert document["proposed_head_oid"] not in {base_commit_oid, second_commit_oid}
    snapshot_commit = document["proposed_head_oid"]
    for relative_path, expected_content in {
        "first.py": "one\n",
        "second.py": "two\n",
        "current.py": "three\n",
    }.items():
        snapshot_content = subprocess.run(
            ["git", "show", f"{snapshot_commit}:{relative_path}"],
            cwd=git_repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert snapshot_content == expected_content


def test_explicit_proposed_ref_rejects_uncommitted_worktree(
    git_repository: Path, policy_dir: Path
) -> None:
    (git_repository / "dirty").write_text("nope\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "review",
            "--proposed",
            "HEAD",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
    assert "omit --proposed" in result.stderr


def test_explicit_refs_work_when_current_branch_has_no_first_commit(
    tmp_path: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "unborn"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "-b", "main", str(repository)],
        check=True,
        capture_output=True,
    )
    for config_name, config_value in (
        ("user.name", "Worktree Review Test"),
        ("user.email", "worktree-review-test@example.com"),
    ):
        subprocess.run(
            ["git", "config", config_name, config_value],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    empty_tree_oid = subprocess.run(
        ["git", "mktree"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        input="",
    ).stdout.strip()
    explicit_commit_oid = subprocess.run(
        ["git", "commit-tree", empty_tree_oid, "-m", "explicit source"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for branch_name in ("target", "proposed"):
        subprocess.run(
            ["git", "update-ref", f"refs/heads/{branch_name}", explicit_commit_oid],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "review",
            "--target",
            "target",
            "--proposed",
            "proposed",
            "--repository",
            str(repository),
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
    assert document["target_ref"] == "target"
    assert document["proposed_ref"] == "proposed"
    assert document["target_head_oid"] == explicit_commit_oid
    assert document["proposed_head_oid"] == explicit_commit_oid


def test_explicit_worktree_named_ref_is_not_mislabeled_as_snapshot(
    git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(
        ["git", "branch", "WORKTREE"],
        cwd=git_repository,
        check=True,
        capture_output=True,
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "review",
            "--proposed",
            "WORKTREE",
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
    assert document["proposed_ref"] == "WORKTREE"
    assert document["proposed_source"] == "committed-ref"


def test_target_and_recent_commits_are_mutually_exclusive(
    git_repository: Path, policy_dir: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--target",
            "main",
            "--commits",
            "2",
            "--repository",
            str(git_repository),
            "--policy",
            str(policy_dir / "review-policy.yaml"),
            "--compute-policy",
            str(policy_dir / "compute-policy.yaml"),
        ],
    )
    assert result.exit_code == int(CliExitCode.INVALID_INVOCATION)
    assert "cannot be used together" in result.stderr


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
