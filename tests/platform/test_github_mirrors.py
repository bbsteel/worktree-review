from __future__ import annotations

from pathlib import Path

import pytest
from tests.gitutil import head_oid

from worktree_review.platform.github.mirrors import (
    MirrorError,
    RepositoryMirrorManager,
    mirror_directory_name,
)


def test_repository_full_name_is_not_a_path() -> None:
    assert mirror_directory_name("octo/example") == "octo__example.git"
    with pytest.raises(MirrorError, match="filesystem path"):
        mirror_directory_name("/tmp/evil")
    with pytest.raises(MirrorError, match="path traversal"):
        mirror_directory_name("octo/../etc")


@pytest.mark.asyncio
async def test_mirror_fetches_oids_into_installation_isolated_path(
    tmp_path: Path, git_repository: Path
) -> None:
    oid = await _head(git_repository)
    manager = RepositoryMirrorManager(tmp_path / "mirrors")
    first = await manager.materialize(
        installation_id=7,
        repository_full_name="octo/example",
        clone_url=str(git_repository),
        required_oids=(oid,),
    )
    other = await manager.materialize(
        installation_id=8,
        repository_full_name="octo/example",
        clone_url=str(git_repository),
        required_oids=(oid,),
    )
    assert first != other
    assert first.name == "octo__example.git"
    assert "octo/example" not in str(first).replace("octo__example", "")
    await manager.verify_oids(first, (oid,))
    with pytest.raises(MirrorError, match=r"does not match required"):
        await manager.verify_oids(first, (oid[:12],))
    with pytest.raises(MirrorError, match="not present"):
        await manager.verify_oids(first, ("0" * 40,))
    manager.cleanup(installation_id=7, repository_full_name="octo/example")
    assert not first.exists()


async def _head(repository: Path) -> str:
    return head_oid(repository)
