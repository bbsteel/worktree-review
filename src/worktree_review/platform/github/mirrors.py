"""Installation-scoped Git mirrors. Repository full name is identity, never a Path."""

from __future__ import annotations

import shutil
from pathlib import Path

from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.git import GitCliError, resolve_commit, run_git


class MirrorError(RuntimeError):
    """The mirror layout or fetched objects are not safe to use as repository_path."""


def mirror_directory_name(repository_full_name: str) -> str:
    if repository_full_name.startswith("/") or repository_full_name.startswith("~"):
        raise MirrorError("repository full name must not be treated as a filesystem path")
    if ".." in repository_full_name.split("/"):
        raise MirrorError("repository full name must not contain path traversal")
    parts = repository_full_name.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise MirrorError("repository full name must be owner/name")
    owner, name = parts
    if any(separator in owner or separator in name for separator in ("\\", "\0")):
        raise MirrorError("repository full name contains invalid characters")
    return f"{owner}__{name}.git"


class RepositoryMirrorManager:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def mirror_path(self, *, installation_id: int, repository_full_name: str) -> Path:
        directory = mirror_directory_name(repository_full_name)
        path = (self.root / str(installation_id) / directory).resolve()
        if not path.is_relative_to(self.root):
            raise MirrorError("mirror path escaped the manager root")
        return path

    async def materialize(
        self,
        *,
        installation_id: int,
        repository_full_name: str,
        clone_url: str,
        required_oids: tuple[str, ...],
    ) -> Path:
        """Fetch the specified OIDs into an installation-isolated bare mirror.

        ``clone_url`` must come from the trusted GitHub API, not pull-request content.
        """
        if clone_url.startswith("/") and "github.com" not in clone_url:
            # Local file remotes are allowed for tests; PR bodies still cannot pick the dir
            # because callers never pass webhook-controlled paths.
            pass
        path = self.mirror_path(
            installation_id=installation_id, repository_full_name=repository_full_name
        )
        _ensure_parent(path)
        try:
            if not _bare_mirror_exists(path):
                await run_git("clone", "--bare", clone_url, str(path), cwd=self.root)
            await run_git("fetch", "--force", "origin", "+refs/*:refs/*", cwd=path)
        except GitCliError as exc:
            raise MirrorError(f"cannot update repository mirror: {exc}") from exc
        await self.verify_oids(path, required_oids)
        return path

    async def verify_oids(self, repository_path: Path, oids: tuple[str, ...]) -> None:
        resolved = _managed_path(self.root, repository_path)
        for oid in oids:
            try:
                found = await resolve_commit(oid, resolved)
            except (GitCliError, InvalidInvocationError) as exc:
                raise MirrorError(f"required object {oid} is not present in the mirror") from exc
            if found != oid and not found.startswith(oid):
                raise MirrorError(f"mirror object {found} does not match required {oid}")

    def cleanup(self, *, installation_id: int, repository_full_name: str) -> None:
        path = self.mirror_path(
            installation_id=installation_id, repository_full_name=repository_full_name
        )
        if path.exists():
            shutil.rmtree(path)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _bare_mirror_exists(path: Path) -> bool:
    return (path / "HEAD").is_file()


def _managed_path(root: Path, repository_path: Path) -> Path:
    resolved = repository_path.resolve()
    if not resolved.is_relative_to(root):
        raise MirrorError("repository_path is not a managed mirror")
    return resolved
