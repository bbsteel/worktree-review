"""Deterministic local-cli provider for demo snapshot generation. No network."""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    request = json.load(sys.stdin)
    mode = os.environ.get("WORKTREE_REVIEW_DEMO_MODE", "passed")
    dimension_id = request.get("dimension_id")
    findings: list[dict[str, object]] = []
    if mode == "blocked" and dimension_id == "security":
        findings.append(
            {
                "path": "src/auth.py",
                "start_line": 2,
                "end_line": 2,
                "quoted_text": "    return True  # unsigned fallback",
                "severity": "major",
                "evidence_band": "supported",
                "problem_statement": "The unsigned fallback branch accepts the request.",
                "expected_impact": "Callers can skip signature checks on the merge candidate.",
                "repair_guidance": "Reject requests that fail signature verification.",
            }
        )
    json.dump({"findings": findings}, sys.stdout)


if __name__ == "__main__":
    main()
