from __future__ import annotations

import subprocess
from pathlib import Path


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def head_oid(repository: Path) -> str:
    return git(repository, "rev-parse", "HEAD").strip()


def commit_files(repository: Path, files: dict[str, str], message: str) -> str:
    for relative, content in files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        git(repository, "add", relative)
    git(repository, "commit", "-m", message)
    return head_oid(repository)


def checkout_new_branch(repository: Path, name: str) -> None:
    git(repository, "checkout", "-b", name)
