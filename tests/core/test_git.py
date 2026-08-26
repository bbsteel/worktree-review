from __future__ import annotations

import pytest

from mergegate.core.errors import GitRequiredError
from mergegate.core.git import MIN_GIT_VERSION, parse_git_version, require_git_version


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
