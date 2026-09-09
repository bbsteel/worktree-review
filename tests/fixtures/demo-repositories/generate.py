"""Generate schema-valid local Pipeline snapshots for the Web UI prototype."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import yaml

from worktree_review.schemas import CLI_RESULT_SCHEMA_ID, load_schema

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = ROOT / "frontend" / "src" / "data" / "snapshots"
PROVIDER = Path(__file__).with_name("local_provider.py")


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "demo@worktree-review.example")
    git(path, "config", "user.name", "Worktree Review Demo")


def commit_files(repository: Path, files: dict[str, str], message: str) -> None:
    for relative, content in files.items():
        file_path = repository / relative
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        git(repository, "add", relative)
    git(repository, "commit", "-m", message)


def write_policies(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    review_policy = directory / "review-policy.yaml"
    config = directory / "local-config.yaml"
    review_policy.write_text(
        """\
schema: worktree-review.review-policy/v1
version: 0.1.0
required_dimensions:
  - correctness
  - security
blocking_severities:
  - critical
  - major
minimum_blocking_evidence_band: supported
""",
        encoding="utf-8",
    )
    config.write_text(
        yaml.safe_dump(
            {
                "provider": "local-cli",
                "command": [sys.executable, str(PROVIDER)],
                "data_destination": "local command stdin/stdout",
                "known_retention": "none — demo local-cli provider",
            }
        ),
        encoding="utf-8",
    )
    return review_policy, config


def run_review(
    repository: Path,
    *,
    config: Path,
    policy: Path,
    mode: str,
    target: str | None = None,
    proposed: str | None = None,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "worktree_review",
        "review",
        "--repository",
        str(repository),
        "--config",
        str(config),
        "--policy",
        str(policy),
        "--format",
        "json",
    ]
    if target:
        command.extend(["--target", target])
    if proposed:
        command.extend(["--proposed", proposed])
    env = os.environ.copy()
    env["WORKTREE_REVIEW_DEMO_MODE"] = mode
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if not completed.stdout.strip():
        raise RuntimeError(
            f"worktree-review produced no JSON for mode={mode}\n"
            f"exit={completed.returncode}\nstderr={completed.stderr}"
        )
    return json.loads(completed.stdout)


def validate_cli_result(document: dict[str, object]) -> None:
    jsonschema.validate(instance=document, schema=load_schema(CLI_RESULT_SCHEMA_ID))


def sidecar(document: dict[str, object], case_key: str) -> dict[str, object]:
    disclosure = document["compute_policy_disclosure"]
    assert isinstance(disclosure, dict)
    review_policy = document["review_policy_version"]
    compute_policy = document["compute_policy_version"]
    assert isinstance(review_policy, dict)
    assert isinstance(compute_policy, dict)
    return {
        "caseKey": case_key,
        "provenance": "pipeline-snapshot",
        "badge": "Pipeline snapshot · local",
        "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resultSchema": document["schema"],
        "reviewPolicy": review_policy,
        "computePolicy": compute_policy,
        "provider": disclosure.get("provider"),
        "model": disclosure.get("model"),
        "providerConfigurationFingerprint": disclosure.get("provider_configuration_fingerprint"),
        "dataDestination": disclosure.get("data_destination"),
        "knownRetention": disclosure.get("known_retention"),
    }


DISPLAY_REPOSITORIES = {
    "passed": "demo/passed-local",
    "blocked": "demo/blocked-local",
    "error_merge_conflict": "demo/error-merge-conflict",
}


def redact_ephemeral_paths(case_key: str, document: dict[str, object]) -> dict[str, object]:
    """Replace generation-time temp paths with stable demo identities."""
    display = DISPLAY_REPOSITORIES[case_key]
    serialized = json.dumps(document)
    source = document.get("source_repository")
    if isinstance(source, str) and source:
        serialized = serialized.replace(source, display)
    disclosure = document.get("compute_policy_disclosure")
    if isinstance(disclosure, dict):
        model = disclosure.get("model")
        if isinstance(model, str) and model:
            serialized = serialized.replace(model, "python")
    redacted = json.loads(serialized)
    if not isinstance(redacted, dict):
        raise TypeError("redacted snapshot is not an object")
    return redacted


def write_snapshot(case_key: str, document: dict[str, object]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    redacted = redact_ephemeral_paths(case_key, document)
    payload = {"metadata": sidecar(redacted, case_key), "result": redacted}
    (SNAPSHOT_DIR / f"{case_key}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def generate(output_root: Path) -> dict[str, dict[str, object]]:
    policies = output_root / "trusted-policies"
    review_policy, config = write_policies(policies)

    passed_repo = output_root / "passed-repo"
    init_repo(passed_repo)
    commit_files(passed_repo, {"README": "hello\n"}, "initial")
    git(passed_repo, "checkout", "-b", "feature/safe")
    commit_files(passed_repo, {"src/ok.py": "VALUE = 1\n"}, "safe change")

    blocked_repo = output_root / "blocked-repo"
    init_repo(blocked_repo)
    commit_files(blocked_repo, {"README": "auth\n"}, "initial")
    git(blocked_repo, "checkout", "-b", "feature/unsigned")
    commit_files(
        blocked_repo,
        {"src/auth.py": "def accept(request):\n    return True  # unsigned fallback\n"},
        "unsigned fallback",
    )

    error_repo = output_root / "error-repo"
    init_repo(error_repo)
    commit_files(error_repo, {"src/app.py": "version = 1\n"}, "base")
    git(error_repo, "checkout", "-b", "feature/broken-merge")
    commit_files(error_repo, {"src/app.py": "version = 2\n"}, "proposed")
    git(error_repo, "checkout", "main")
    commit_files(error_repo, {"src/app.py": "version = 3\n"}, "target change")

    passed = run_review(
        passed_repo,
        config=config,
        policy=review_policy,
        mode="passed",
        target="main",
        proposed="feature/safe",
    )
    blocked = run_review(
        blocked_repo,
        config=config,
        policy=review_policy,
        mode="blocked",
        target="main",
        proposed="feature/unsigned",
    )
    error = run_review(
        error_repo,
        config=config,
        policy=review_policy,
        mode="error",
        target="main",
        proposed="feature/broken-merge",
    )

    for document in (passed, blocked, error):
        validate_cli_result(document)

    write_snapshot("passed", passed)
    write_snapshot("blocked", blocked)
    write_snapshot("error_merge_conflict", error)
    return {"passed": passed, "blocked": blocked, "error_merge_conflict": error}


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wr-demo-repos-") as temp:
        generate(Path(temp))
    print(f"Wrote snapshots to {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()
