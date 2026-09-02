from __future__ import annotations

import pytest

from worktree_review.platform.github.mapping import commentable_new_side_lines


def test_commentable_new_side_lines_tracks_each_file_and_hunk() -> None:
    unified_diff = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 first
+inserted
 second
@@ -8 +9,2 @@
 old context
+another
diff --git a/docs/read me.md b/docs/read me.md
index 3333333..4444444 100644
--- a/docs/read me.md
+++ b/docs/read me.md
@@ -2,0 +2,2 @@
+one
+two
"""

    assert commentable_new_side_lines(unified_diff) == frozenset(
        {
            ("src/app.py", 1),
            ("src/app.py", 2),
            ("src/app.py", 3),
            ("src/app.py", 9),
            ("src/app.py", 10),
            ("docs/read me.md", 2),
            ("docs/read me.md", 3),
        }
    )


def test_commentable_new_side_lines_handles_added_and_deleted_files() -> None:
    unified_diff = """\
diff --git a/removed.txt b/removed.txt
deleted file mode 100644
index 1111111..0000000
--- a/removed.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-first
-second
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,1 @@
+new
"""

    assert commentable_new_side_lines(unified_diff) == frozenset({("new.txt", 1)})


def test_commentable_new_side_lines_decodes_git_quoted_paths() -> None:
    unified_diff = """\
--- "a/docs/na\\303\\257ve.md"
+++ "b/docs/na\\303\\257ve.md"
@@ -1 +1 @@
-old
+new
"""

    assert commentable_new_side_lines(unified_diff) == frozenset({("docs/naïve.md", 1)})


@pytest.mark.parametrize(
    "unified_diff, message",
    [
        ("@@ -1 +1 @@\n+line\n", "no destination path"),
        ('+++ "b/broken\n@@ -1 +1 @@\n', "unterminated"),
        ("+++ b/file\n@@ malformed\n", "invalid unified-diff hunk"),
        ("+++ b/../file\n@@ -1 +1 @@\n", "invalid unified-diff destination path"),
    ],
)
def test_commentable_new_side_lines_rejects_ambiguous_diff(
    unified_diff: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        commentable_new_side_lines(unified_diff)
