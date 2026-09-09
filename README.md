# Worktree Review

Review the worktree, not just the diff. Worktree Review constructs the exact
merge result, examines it in full-tree context, and produces an evidence-bound
decision for local use or authoritative GitHub gating.

| Entry point | Role |
| --- | --- |
| `worktree-review` | Local CLI. One-shot review of current worktree changes, recent commits, or an explicit committed head. |
| `worktree-review-server` | GitHub App: webhook receiver and review workers in one process. |

Product semantics live in `worktree_review.core`. Platform adapters only map transport (terminal, GitHub checks/webhooks) onto core types. See `docs/PRD.md` and `docs/TECH-DESIGN.md`.

This repository currently contains the **stage-one core**: domain identities,
policy validation, exact merge construction, verified read-only Review Worktree
materialization, context gathering, provider-backed review dimensions, bounded
provider calls and usage metering, finding verification, deterministic gate evaluation, CLI output, and
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

By default the CLI reviews current worktree changes against `HEAD`. Review Policy is
built in; provider configuration lives in a trusted `config.yaml` outside the
reviewed worktree.

See the [CLI usage and configuration guide](USAGE.md) or the
[中文说明](USAGE.zh-CN.md) for policy fields, provider credentials, source
selection, output, and troubleshooting.

```bash
uv run worktree-review init
uv run worktree-review
```

`init` interactively writes the trusted default configuration and checks a local
executable without running it. The minimal `config.yaml` contains a provider,
key, and model (with an optional custom URL), or a local CLI command plus one of
the built-in local adapters. Review Policy is built in. Run
`uv run worktree-review prompts --dimension security` to inspect the
product-owned prompt layers used by a dimension.

Use `uv run worktree-review review --config /path/to/config.yaml` when an
explicit command or configuration path is preferred.

Use `--target main` to review the current worktree as it would merge into `main`,
`--commits 3` to review the last three commits plus current worktree changes, or
`--proposed feature` to review an explicit committed ref. The explicit `--proposed`
form requires a clean worktree; omit it to include current changes. A clean worktree
means the current change set is empty. `--format json` emits
`worktree-review.cli.result/v1`. For the default source, the result labels
`proposed_ref` as `WORKTREE` and reports the immutable snapshot commit in
`proposed_head_oid`; `proposed_source` distinguishes this from a committed ref
with the same display name.

Exit codes (TECH-DESIGN D10):

| Code | Meaning |
| --- | ---: |
| 0 | `Passed` |
| 1 | `Blocked` |
| 2 | `Error` |
| 3 | Invalid invocation (unresolvable refs, policy inside the repo, git too old, incompatible source-selection flags, or an unrepresentable worktree snapshot) |

The CLI never produces `Passed with bypass`.

The minimal [configuration example](config.example.yaml), advanced policy
examples, and the complete [usage guide](USAGE.md) are available in the
repository.

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
  prompts/          product-owned, inspectable prompt layers
  schemas/         versioned JSON Schema for config, policy, findings, and results
  cli.py           `worktree-review` entry
  server/          `worktree-review-server` entry (FastAPI)
```
