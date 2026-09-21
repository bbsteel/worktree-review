from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from worktree_review.schemas import CLI_RESULT_SCHEMA_ID, load_schema

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "src" / "data" / "snapshots"


def test_committed_pipeline_snapshots_validate_and_stay_local() -> None:
    schema = load_schema(CLI_RESULT_SCHEMA_ID)
    files = {
        "passed": SNAPSHOT_DIR / "passed.json",
        "blocked": SNAPSHOT_DIR / "blocked.json",
        "error_merge_conflict": SNAPSHOT_DIR / "error_merge_conflict.json",
    }
    for path in files.values():
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = payload["result"]
        jsonschema.validate(instance=result, schema=schema)
        serialized = json.dumps(result)
        assert payload["metadata"]["provenance"] == "pipeline-snapshot"
        assert payload["metadata"]["badge"] == "Pipeline snapshot · local"
        assert result["schema"] == "worktree-review.cli.result/v1"
        assert "/tmp/" not in serialized
        assert "github-pull-request" not in serialized
        assert str(result["source_repository"]).startswith("demo/")

    passed = json.loads(files["passed"].read_text(encoding="utf-8"))["result"]
    assert passed["gate_state"] == "Passed"
    blocked = json.loads(files["blocked"].read_text(encoding="utf-8"))["result"]
    assert blocked["gate_state"] == "Blocked"
    assert len(blocked["findings"]) == 1
    error = json.loads(files["error_merge_conflict"].read_text(encoding="utf-8"))["result"]
    assert error["gate_state"] == "Error"
    assert error["review_identity"] is None
    assert error["merge_tree_oid"] is None
