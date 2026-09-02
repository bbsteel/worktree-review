# Worktree Review

Review the worktree, not just the diff. Worktree Review constructs the exact
merge result, examines it in full-tree context, and produces an evidence-bound
decision for local use or authoritative GitHub gating.

| Entry point | Role |
| --- | --- |
| `worktree-review` | Local CLI. One-shot review of a committed head against an explicit target ref. |
| `worktree-review-server` | GitHub App: webhook receiver and review workers in one process. |

Product semantics live in `worktree_review.core`. Platform adapters only map transport (terminal, GitHub checks/webhooks) onto core types. See `docs/PRD.md` and `docs/TECH-DESIGN.md`.

This repository currently contains the **stage-one core**: domain identities,
policy validation, exact merge construction, verified read-only Review Worktree
materialization, context gathering, provider-backed review dimensions, budget
metering, finding verification, deterministic gate evaluation, CLI output, and
fail-closed stage records. The server also has the authoritative Attempt/CAS
state transitions, authorized retry boundary, and an injected GitHub Checks
payload/publication adapter; the embedded pgqueuer review worker and end-to-end
publication wiring remain to be implemented.

## Requirements

- Python ≥ 3.12
- Git ≥ 2.38 (`git merge-tree --write-tree`)
- [uv](https://docs.astral.sh/uv/) for development
- PostgreSQL 16 for the GitHub service (not required for the CLI)

## Development

```bash
uv sync --extra server
uv run ruff check src tests
uv run ruff format src tests
uv run mypy
uv run pytest
```

CLI only (no FastAPI / Postgres extra):

```bash
uv sync
uv run worktree-review --help
```

Install git hooks:

```bash
uv run pre-commit install
```

## CLI

Review a committed local head. Policy files must live **outside** the reviewed worktree.

```bash
uv run worktree-review review \
  --target main \
  --policy /path/to/review-policy.yaml \
  --compute-policy /path/to/compute-policy.yaml
```

`--proposed` defaults to `HEAD`. `--format json` emits `worktree-review.cli.result/v1`.

Exit codes (TECH-DESIGN D10):

| Code | Meaning |
| --- | ---: |
| 0 | `Passed` |
| 1 | `Blocked` |
| 2 | `Error` |
| 3 | Invalid invocation (dirty worktree, unresolvable refs, policy inside the repo, git too old, bad flags) |

The CLI never produces `Passed with bypass`.

Example policies are in `examples/`.

## Server

```bash
uv sync --extra server
docker compose up --build
```

The image runs `worktree-review-server`. `GET /healthz` is the liveness probe.
The server validates GitHub webhook signatures and maps authorized retry
actions into new Attempts. GitHub Checks payloads and authenticated create/update
transport are implemented behind an adapter, but the review worker has not yet
connected the shared pipeline to that adapter. To enable the retry runtime, configure
`WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET`,
`WORKTREE_REVIEW_DATABASE_URL`, `WORKTREE_REVIEW_GITHUB_TOKEN`, and
`WORKTREE_REVIEW_REVIEW_POLICY_PATH`; without the webhook secret retry is
explicitly disabled, while an incomplete enabled configuration fails startup.

## Layout

```
src/worktree_review/
  core/            platform-independent product semantics
  platform/cli/    terminal report, JSON result, exit codes
  platform/github/ checks, comments, webhooks, authz, inline mapping
  schemas/         versioned JSON Schema for policy and CLI results
  cli.py           `worktree-review` entry
  server/          `worktree-review-server` entry (FastAPI)
```
