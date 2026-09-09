# Worktree Review Technical Design — v1

- Status: First-version technical landing plan for the first-stage PRD
- Date: 2026-08-27
- Companion document: `docs/PRD.md` (normative first-stage product contract)
- Chinese translation: `docs/TECH-DESIGN.zh-CN.md`
- Scope: architecture, language, third-party components, identity/attempt
  persistence, authoritative publication semantics, the first-stage user config,
  and the inspectable prompt hierarchy. Detailed server schemas, exact prompt
  wording beyond the required layers, and interaction design remain follow-up
  work.

This document resolves the decisions the PRD explicitly defers (PRD §23).
Every choice below must preserve the PRD's normative invariants: exact merge
candidate or no review, identity-bound decisions, fail-closed `Error`,
complete review or visible failure, read-only analysis, and policy that never
comes from the reviewed repository.

## Conceptual model used by this design

This design uses the PRD terminology as distinct persistence and concurrency
boundaries:

| Concept | Technical role |
| --- | --- |
| Review Worktree | Read-only, verified filesystem materialization of a successful merge candidate. It provides full-tree review context but is not required to be a Git linked worktree. |
| Review Request Key | Available before merge construction; keys scheduling, construction-failure reporting, and audit by repository, target ref, resolved heads, and Review Policy version. |
| Merge Candidate Identity | Finalized only after `git merge-tree` returns a valid resulting tree OID. |
| Review Identity | Merge Candidate Identity plus Review Policy version; defines what a review conclusion applies to. |
| Review Context | An immutable, content-addressed snapshot gathered by one Attempt; never used as a substitute for Review Identity. |
| Review Attempt | One pipeline execution with its own Attempt ID, Compute Policy version, model/usage provenance, and result. |
| Authoritative Attempt | The Attempt ID stored as current for a platform change request; only this Attempt may mutate its Standing Decision. |
| Standing Decision | The platform gate row and published check derived from the Authoritative Attempt after atomically checking the Review Request Key and, when constructed, Review Identity. Construction `Error` therefore remains representable without a fake identity. |

The database must never infer attempt authority from completion time. A later
completion can belong to an older, superseded attempt.

## 1. Language selection

### Decision: Python (single language for core, CLI, and GitHub service)

One repository, one Python package with a shared `worktree_review.core`, and two
entry points. The GitHub server and its authoritative gate are the first-stage
delivery priority; the CLI shares the same pipeline and deterministic evaluator:

| Entry point | Role |
| --- | --- |
| `worktree-review` | Local CLI surface (PRD §4, §21.3). Distributed via PyPI (`uv tool install worktree-review` / pipx). |
| `worktree-review-server` | GitHub App: webhook receiver + review workers in one deployable process. Distributed as a Docker image. |

Rationale:

- **Maintainer velocity is the deciding factor.** Stage-one code is dominated
  by prompting, context assembly, and finding processing — code that will
  churn constantly. The primary maintainer is fluent in Python and not in Go;
  iteration speed on the churn-heavy 80% outweighs Go's static-distribution
  advantage on the stable 20%.
- **CLI distribution is solved well enough.** Target users are developers;
  `uv`/`pipx` installation with a pinned interpreter requirement (Python
  ≥ 3.12) is an established pattern (pre-commit, poetry, semgrep). A
  PyInstaller single binary remains a later packaging option if non-Python
  users appear.
- **Concurrency is I/O-bound.** Required review dimensions run concurrently
  (PRD §11.1), but every concurrent task waits on LLM API calls; `asyncio`
  with `TaskGroup` covers this fully. Go's concurrency advantage is real for
  CPU-bound work, which this product does not have.
- **Type safety is enforced by discipline, not only the compiler.** The
  deterministic gate evaluator (PRD §9.5) must be a pure, auditable function.
  Python reaches "good enough to trust" here via: Pydantic v2 models at every
  boundary, JSON Schema as the single source of truth for policy and result
  formats (Python types generated from schemas), mypy strict across the repo,
  and Hypothesis property tests on the gate evaluator.
- **The LLM ecosystem is strongest in Python.** The official `anthropic` and
  `openai` SDKs are first-class citizens; provider-native structured output
  and detailed usage metering are available on day one.
- **Git is shelled out, not linked.** All merge-candidate work goes through
  the system `git` CLI (see D2), so no language needs a libgit2 binding.

### Alternatives considered

| Language | Why not |
| --- | --- |
| Go | Best CLI distribution (single static binary) and strong static typing, but the primary maintainer is not fluent in it, and the churn-heavy parts of this codebase (prompting, context assembly, finding logic) iterate much faster in Python. Revisit if CLI distribution to non-developer users becomes a requirement. |
| TypeScript/Node | Best GitHub API ergonomics (Octokit), but CLI distribution requires bundlers/SEA hacks, runtime type safety needs a validation layer everywhere, and two-runtime risk (bun vs node) adds support surface. Revisit only if the product pivots to a GitHub Action form. |
| Rust | Best binary story and safety, but slows iteration on prompting/analysis code that will churn heavily in stage one; LLM SDK maturity is lowest. Keep as an option if Review Worktree isolation ever needs a native sandbox helper. |

## 2. Architecture selection

### 2.1 Top-level shape

```
┌───────────────────────────────────────────────────────────────┐
│ Surfaces (entry points of the single `worktree-review` package)      │
│   worktree-review    (CLI, PRD §21.3; Typer app)               │
│   worktree-review-server   (GitHub App, PRD §21.2; FastAPI)          │
├───────────────────────────────────────────────────────────────┤
│ Adapters (thin; may not reinterpret product semantics, §8.12)  │
│   worktree_review.platform.github  checks, comments, webhooks, authz │
│   worktree_review.platform.cli     terminal report, JSON result, exit│
├───────────────────────────────────────────────────────────────┤
│ Core (platform-independent; both surfaces import this)         │
│   worktree_review.core.identity    merge-candidate / review identity │
│   worktree_review.core.candidate   merge construction (git merge-tree)│
│   worktree_review.core.review_worktree  isolated Review Worktree     │
│   worktree_review.core.policy      Review/Compute Policy load+validate│
│   worktree_review.core.config      minimal provider config + defaults│
│   worktree_review.core.context     mandatory/optional/excluded gather│
│   worktree_review.core.dimension   required review dimensions        │
│   worktree_review.core.provider    LLM provider abstraction + limits │
│   worktree_review.prompts           product-owned prompt hierarchy    │
│   worktree_review.core.findings    verify, dedup, classify           │
│   worktree_review.core.gate        deterministic gate evaluation     │
│   worktree_review.core.report      surface-neutral result model      │
│   worktree_review.core.pipeline    the 9-stage pipeline (PRD §21.1)  │
├───────────────────────────────────────────────────────────────┤
│ Infrastructure                                                 │
│   system git CLI · PostgreSQL (server state) · pgqueuer jobs   │
│   LLM provider APIs · detect-secrets redaction · structlog/OTel│
└───────────────────────────────────────────────────────────────┘
```

The PRD's portability rule (§8.12) is enforced structurally: everything the
PRD calls a product semantic lives in `worktree_review.core`; adapters only map
transport concepts (webhook payloads, checks API, terminal output, exit
codes) onto core types. The package uses a `src/worktree_review/` layout; the CLI
and server share one distribution, with server-only dependencies behind a
`worktree-review[server]` extra.

### 2.2 Architecture decisions

**D1 — GitHub App, not a GitHub Action.**
The first stage requires a *standing* gate decision with immediate
invalidation (§8.2), durable per-installation policy stored outside the
reviewed repository (§8.9), an auditable bypass action bound to GitHub
authorization roles (§16), and target-branch push events so a target-head
change invalidates standing decisions. None of these fit an Action's
run-scoped, repo-config-loaded, ephemeral model. An App receives the events,
holds installation-scoped policy, publishes durable checks, and can gate the
bypass action on `write`/`maintain`/`admin` roles via the permissions API.
Self-hosted first; hosted multi-tenant remains a later-stage decision (§23).

**D2 — Merge candidate via `git merge-tree --write-tree` in a bare object
store.**
Construction must not execute or even check out proposed-change code
(§8.11) and must fail closed on conflict (§8.1). `git merge-tree
--write-tree` (git ≥ 2.38) computes the merge tree purely in the object
database: no worktree, no hooks, no smudge filters, and conflict detection
is exact. Both parent commits and the resulting tree OID are recorded as the
merge-candidate identity (§8.2). Before construction, the attempt carries only
the Review Request Key; conflict or missing objects therefore produce `Error`
without inventing a merge-tree OID or completed Review Identity.

The Review Worktree is materialized from raw tree entries and blob OIDs into a
fresh directory, then verified against the source tree and chmod'd read-only. It
must not use `git archive`, checkout filters, or another mechanism that applies
candidate-controlled `export-ignore`, `export-subst`, smudge, clean, or external
driver behavior. Repository paths may not collide with product-owned markers;
product metadata lives outside the extracted tree. File creation uses
directory-relative operations that reject traversal and never follows a
repository symlink for writes. Symlinks are materialized as link data only.

The product term Review Worktree deliberately borrows the developer intuition
of a complete, isolated Git worktree. The implementation does not use
`git worktree add`: doing so would require a commit/HEAD-shaped checkout and
would introduce repository metadata and checkout behavior that the exact
merge-tree materialization contract does not need.

The Review Worktree is owned by a dedicated unprivileged runtime user (server) or the
invoking user (CLI), with a scrubbed environment: no platform tokens, no
installation tokens, no provider credentials inside the worker's reachable env
(§8.11). We deliberately do **not** use go-git: merge fidelity, rename handling,
and LFS pointer behavior must match real git byte-for-byte. The CLI requires git
≥ 2.38 and fails invocation (exit 3) otherwise. For its default proposed source,
the CLI captures the current worktree through a temporary index and an immutable,
unreachable snapshot commit: tracked files use current filesystem bytes, non-ignored
untracked files are included, ignored files are excluded, and clean/smudge filters
are disabled while hashing. The user's index and worktree are never changed. A
clean worktree reuses its current `HEAD` commit. An explicit committed proposed ref
cannot be combined with uncommitted worktree changes, preventing silent omission.

**D3 — One shared 9-stage pipeline, explicit stage outcomes.**
`worktree_review.core.pipeline` implements PRD §21.1 literally: establish request key
and attempt → merge and finalize identities → Review Worktree → context →
dimensions → verify/dedup → completeness check → gate → publish. The machine
identifier for Review Worktree preparation is `prepare-review-worktree`. That is a
Pre-Alpha in-place update of `worktree-review.cli.result/v1`; the previous wire
value was `prepare-workspace`. Every stage writes an outcome record
(`completed` / `failed` / `not-started`) into an append-only execution record,
so a fatal failure can never be hidden by later output (§21.1) and every surface
can render per-stage completion (§19). A fatal stage failure short-circuits to
`Error`; partial findings from completed dimensions remain visible but carry the
review's `Error` state and cannot be bypassed (§16, §18).

For GitHub, stage 1 transactionally creates the attempt and makes its ID
authoritative before work is queued. Stage 9 uses a compare-and-set publication:
the persisted authoritative attempt ID and Review Request Key must still match,
plus Review Identity after successful construction. Failure of any applicable
comparison converts publication to an audit-only superseded result, never a
standing decision.

**D4 — Deterministic, pure gate evaluator.**
`worktree_review.core.gate` is a pure function
`(dimension outcomes, coverage, findings, bypasses, Review Policy) →
GateState`. No model call participates; model output may only influence
*which findings exist*, never the mapping to the decision (§9.5). The
evaluator is table-driven and property-tested (e.g., "no unresolved blocking
finding ⇒ not `Blocked`", "any incomplete required dimension ⇒ `Error`").

**D5 — Policy as versioned, content-addressed YAML under Worktree Review control.**
Review Policy and Compute Policy are separate YAML documents with separate
versions (§8.2: Compute Policy changes do not invalidate standing
decisions). Each document carries a semver; its *version identity* is
`semver + SHA-256 of canonical bytes`. Storage:

- CLI: `--policy` is optional and otherwise resolves to the product-owned built-in
  Review Policy. Normal provider configuration is a minimal `--config` YAML file
  at `~/.config/worktree-review/config.yaml` (or an explicit path), containing
  a remote provider/key/model (with an optional custom URL) or a local CLI
  command. Local commands select one of the trusted product adapters
  `worktree-json`, `prompt-json`, or `prompt-text-json`; the default is the
  Worktree Review JSON stdin/stdout protocol. The normal path derives a hard
  4096-token per-call output limit and no dollar budget. It also derives a
  non-secret fingerprint over the complete local command configuration, and
  carries optional local-command destination and retention disclosures.
  `--compute-policy` remains an advanced path for deployments that need direct
  compute controls; its external schema accepts remote providers only. Every
  custom policy/config path must be outside the reviewed repository (§8.9).
- GitHub: per-installation rows in Postgres, edited outside the reviewed
  repo; every review records the exact policy version hashes it used.

All file-backed policy/config load paths validate against a versioned JSON Schema
and fail closed on invalid input. The built-in Review Policy is product code and
is validated at load time. Repository files like `AGENTS.md`/`CLAUDE.md` are
loaded only as untrusted *context* (§8.10), never as policy or configuration.

**D6 — Findings via provider-constrained structured output, with grounded
evidence checks.**
Each review dimension calls the model with a JSON-Schema-constrained
response (provider-native structured outputs / tool use). The verify stage
(§21.1 step 6) is partly deterministic: every finding's supporting evidence
must reference spans (path + line range + quoted text) that actually exist in
the declared typed source and matching immutable snapshot. The first-stage
sources are `review-worktree`, `target-tree`, `merge-diff`, and `metadata`;
`change_kind` is carried when it is known. `context_class` is a presentation
label, not provenance. A target-tree body therefore cannot ground a span
declared against the Review Worktree, even when the quote is identical.
Ungrounded claims cannot carry `supported` or `verified` bands (§8.5, §13).
Grounding derives at most `supported`; `verified` requires independent trusted
verification provenance outside the provider output, so provider-declared
`verified` is capped in the first-stage pipeline. All findings are verified
before grouping, and duplicate groups merge conservatively (strongest
evidence and severity) so input/provider order cannot discard a stronger
finding. Deduplication is deterministic fingerprinting over (path, normalized
span, category, problem hash); fingerprints are always recomputed locally,
using a sentinel path when no valid span exists. This keeps "self-reported
model certainty is not evidence" (§13) enforceable in code rather than in
prompts.

Prompt resources are product-owned package data under `worktree_review.prompts`.
Each dimension composes the ordered layers `00-product`, `10-safety`, `20-review`,
`30-dimensions/<dimension>`, and `40-output`; the CLI exposes the effective layers
through `worktree-review prompts --dimension <id>`. Prompt resources are never
loaded from the reviewed repository and are not a policy override mechanism.

**D7 — Bounded provider calls and advanced budget enforcement.**
Every Compute Policy carries a hard maximum output token count per provider call.
The normal `--config` path derives `max_output_tokens_per_call: 4096`, records
input estimates without pricing them, and relies on the provider account for
actual spend. It reports the planned call count, estimated input tokens, and
per-call output limit before the first call; measured usage and cost availability
after completion remain explicit. Provider handoff disclosure applies equally to
remote SDK calls and local commands. A local command is not assumed to be
network-free; its command/adapter/destination/retention fingerprint is included
in the derived Compute Policy identity and result.

Advanced `--compute-policy` carries an optional per-review budget for internal
derived policies and a required budget in the external advanced schema (§9.3, §20):

1. *Pre-flight*: estimate input tokens of assembled context with the
   provider tokenizer; if estimate × versioned price table exceeds budget,
   refuse to start with `Error` (budget exhausted), unless Compute Policy
   explicitly permits starting under uncertain price/usage (§20).
2. *In-flight*: meter actual usage from provider response fields after every
   call; stop scheduling further dimensions when the remaining budget cannot
   cover their estimated cost.
3. *Exhaustion*: gate state is `Error`; completed/skipped/unreviewed scope
   is disclosed; findings stay visible but cannot be bypassed (§18).

Usage records distinguish measured, declared, and estimated values (§9.3)
and are persisted per review attempt for audit. A normal configuration does not
turn an unknown provider price into a prediction or a local dollar budget.

**D8 — Server state in PostgreSQL; queue via pgqueuer on the same database.**
The GitHub service needs durable standing decisions, bypass audit records,
and supersede-safe scheduling. Postgres + pgqueuer (an async-native,
Postgres-backed job queue using `LISTEN`/`NOTIFY` and
`SELECT ... FOR UPDATE SKIP LOCKED`) covers both without extra
infrastructure:

- An identity-changing event or authorized same-identity retry creates a fresh
  attempt ID, stores it as the change request's `authoritative_attempt_id`, and
  invalidates the prior standing decision in one transaction before enqueue.
  Jobs are unique by attempt ID, not Review Identity, because a valid retry must
  be able to execute the same identity again.
- Superseded queued jobs are discarded. In-flight work may finish, but stage 9
  atomically compares `authoritative_attempt_id` and current Review Request Key,
  plus Review Identity after successful construction, before changing
  `gate_decisions` or publishing a check. An older same-identity attempt
  therefore cannot overwrite a newer result.
- Publication is a single-use `RUNNING → PUBLISHED` CAS. Repeating the same
  result for the still-standing Attempt returns the original result without a
  second decision; a different result is a state conflict. Each Attempt has at
  most one gate decision by database uniqueness constraint.
- GitHub retry deliveries are idempotent by `(installation_id, delivery_id)`.
  The delivery record and its new Attempt are inserted in the same transaction;
  a redelivery returns the first Attempt and never supersedes it again.
- Provider-call retry controlled by `tenacity` remains inside one attempt.
  Re-executing the complete review after `Error`, changed Compute Policy, or an
  authorized GitHub retry always creates another attempt.
- No Redis/SQS/NATS/Celery in stage one.

The CLI is stateless except an optional local cache directory
(`~/.cache/worktree-review/`) for immutable artifacts keyed by content hash;
caching may never reduce review scope or reuse conclusions (§11.1).

**D9 — Append-only audit events, with published-state self-audit.**
Bypass records, gate transitions, invalidations, policy versions, model
provenance, and cost data are written as append-only audit events
(§8.2, §16). Bypass binds to review identity + finding fingerprint + stated
risk snapshot (problem statement, severity, impact, key evidence); expiry on
identity or Review-Policy change and "materially unchanged" re-match on
re-review are evaluated deterministically from these fields (§16, §9.4).

Worktree Review does not trust the platform-visible standing state it published;
it reconciles it against its own records (the forged-status lesson from
palantir/policy-bot):

- Every published check embeds an *attempt-id fingerprint* (a short hash of
  the review attempt id) in its output, and its details URL resolves to our
  server-rendered view of the database decision. A status or check forged by
  someone with repository write access cannot reproduce the current
  fingerprint.
- The fingerprint is descriptive, not the concurrency guard. Authority comes
  from the transactional `authoritative_attempt_id` compare-and-set in D8;
  check output alone is never trusted to determine which attempt is current.
- On every `status`/check webhook affecting a commit we gate, plus periodic
  sweeps, the server compares the platform-visible state with the
  `gate_decisions` table. A mismatch produces a `standing_state_tampered`
  audit event, triggers immediate re-publication of the correct state, and
  notifies the installation owner. GitHub's ruleset "expected source"
  pinning for required checks is documented as the recommended platform-side
  complement.
- Bypass commands arriving as PR comments are never trusted as text: the
  actor's repository role is verified live via the API at processing time
  (§16), and the authorization outcome is recorded as an immutable audit
  event, unaffected by later comment edits. GitHub-native administrative
  overrides (e.g., an admin merging over a failing required check) are
  recorded as observable audit events whenever the platform surfaces them
  (§19).

The Checks API already namespaces check runs per App, which removes most of
the forgery vector on GitHub; reconciliation remains as defense in depth and
as the mechanism that keeps native overrides visible.

**D10 — CLI contract.**
- Human-readable report to stdout; `--format json` emits the versioned
  machine-readable schema `worktree-review.cli.result/v1` (§19). Pre-Alpha
  may update identifiers in that schema in place; Review Worktree
  preparation is `prepare-review-worktree`, not `prepare-workspace`.
- The CLI reports its call plan before provider calls and includes it with usage
  records in the machine-readable result. Normal configuration reports measured
  input/output tokens when the provider returns them and otherwise directs the
  user to provider account billing for cost.
- `worktree-review init` interactively selects a remote provider/key or local
  command, checks that a local executable is available without executing it, and
  writes a mode-600 trusted default configuration. The plain `worktree-review`
  entry point invokes the same local review as the explicit `review` command.
- Text and JSON modes write non-authoritative preparation, stage, and current
  dimension progress to stderr, including elapsed time after work completes;
  JSON stdout remains exclusively the versioned result document.
- Exit codes: `0` = `Passed`, `1` = `Blocked`, `2` = `Error`,
  `3` = invalid invocation (unresolvable refs, policy inside repo, git too
  old, incompatible source-selection flags, or an unrepresentable worktree
  snapshot). `Passed with bypass` is never produced by the CLI (§4, §11).
- By default the CLI reviews the current worktree snapshot against `HEAD`.
  `--target` selects another target ref, `--commits N` reviews `HEAD~N` through
  the current worktree snapshot, and `--proposed` selects an explicit committed
  proposed ref on a clean worktree. The machine result labels the default source
  as `proposed_ref=WORKTREE`, reports `proposed_source=current-worktree-snapshot`,
  and reports its immutable snapshot commit as `proposed_head_oid`. The target
  and proposed source are captured once before the shared pipeline starts; later
  changes are outside the result.
- `--policy` is optional and uses the built-in Review Policy when omitted. The
  normal `--config` file selects a remote provider/key/model with an optional
  custom URL, or a local CLI command and product adapter; it derives a 4096-token
  per-call output limit and no dollar budget. The advanced `--compute-policy`
  path remains available for direct compute control and accepts remote providers
  only. Before any provider handoff, the CLI prints provider, model, data
  destination, known retention behavior, and the local configuration fingerprint
  when applicable. No feedback or telemetry leaves the CLI without explicit
  opt-in (§22).
- `worktree-review prompts --dimension <id>` prints the trusted product-owned
  prompt hierarchy used for that dimension.
- Every invocation generates an attempt ID. Construction failures emit the
  Review Request Key with `merge_tree_oid: null`; successful construction also
  emits Merge Candidate Identity and Review Identity. No CLI attempt is marked
  authoritative in server state.

**D11 — Untrusted-content and secret hygiene.**
All repository content is data (§8.10): context assembly inserts it as
quoted, delimited model input; reviewer tools and permissions come only from
trusted policy (§8.11). Findings and logs pass through a detect-secrets-based
redaction step before publication (§8.11).

**D12 — Deployment for stage one.**
The server ships as a single Docker image running `worktree-review-server`
(webhook HTTP + embedded pgqueuer workers) beside a Postgres instance; the
CLI ships via PyPI and installs with `uv tool install worktree-review` or pipx.
For development, webhooks arrive via smee.io/ngrok. There is no separate
worker fleet, scheduler, or service mesh in stage one.

**D13 — GitHub inline publication is a tested mapping layer, not an
afterthought.**
Core findings always carry absolute line numbers in the merge-candidate
tree; conversion to GitHub-commentable positions happens only in the GitHub
adapter (the CLI reports absolute paths/lines directly, §19). Mechanics,
following reviewdog's lead:

- We generate the mapping diff ourselves (`git diff` between the resolved
  target head and the merge tree) with controlled flags — fixed prefixes,
  rename detection off — so hunk headers (`@@ -a,b +c,d @@`) are
  predictable. The mapper parses hunk headers to compute which new-side
  absolute lines are commentable: a small, property-testable function, not a
  general-purpose diff parser. (`unidiff` is the fallback library if edge
  cases outgrow it.)
- GitHub only accepts inline comments/annotations on lines present in its
  own three-dot PR diff (merge-base … proposed head). Our findings live in
  the merge-candidate diff (resolved target head … merge tree), which is a
  *different* diff — that difference is precisely PRD §8.1's point. A
  finding on a target-side line introduced after the merge-base is not
  inline-eligible on GitHub even though it is central to the review.
- Degradation ladder, each step disclosed in the coverage output (§8.4,
  §19): inline comment/annotation → file-level comment → check summary with
  full coordinates and the reason inline placement was impossible. No
  finding is silently dropped or silently downgraded.
- Checks annotations are batched at 50 per API request; annotation level
  (`notice`/`warning`/`failure`) maps from finding severity.

**D14 — GitHub retry is a new authoritative attempt, not an identity mutation.**
The first-stage App exposes an authorized retry action for the current review
request. The initial interaction is a Checks requested action; a details-page
action is an equivalent fallback. Processing re-resolves the current refs and
Review Policy, then executes the D8 transaction. If those inputs changed, the
new attempt naturally receives a new request key and later Review Identity; if
they did not, it is a same-identity retry. Changed Compute Policy is recorded on
the new attempt but never added to Review Identity. Authorization outcome,
reason, delivery ID, prior attempt ID, and new attempt ID are append-only audit
fields. GitHub redelivery is acknowledged idempotently by the delivery key.

## 3. Third-party component selection

| Concern | Choice | Why / notes |
| --- | --- | --- |
| Language toolchain | Python ≥ 3.12, `uv` for env/lock/publish | See §1. `uv` covers venvs, lockfile, build, and PyPI upload. |
| Packaging/build | `hatchling` (via uv), `src/worktree_review/` layout | Single package; server-only deps behind the `worktree-review[server]` extra; two console entry points. |
| CLI framework | `typer` | Type-hint-driven commands on top of Click; exit-code control stays ours. |
| HTTP server | `fastapi` + `uvicorn` | Webhook receiver; async-native; OpenAPI for the details/health endpoints. |
| HTTP client | `httpx` (async) | Provider SDKs and GitHub calls share one async client discipline. |
| YAML parsing | `pyyaml` | Policy documents; version hash computed over the canonicalized parsed form, not raw bytes. |
| Schema/validation | `pydantic` v2 + `jsonschema` | JSON Schema is the single source of truth for policy and result formats; Python types generated from schemas; fail-closed on invalid input. |
| Git operations | system `git` CLI ≥ 2.38 via `asyncio` subprocess | `merge-tree --write-tree`, raw tree/blob enumeration, ref resolution. Exactness beats embedding (D2). |
| GitHub API + webhooks | `githubkit` | Async, generated from GitHub's OpenAPI spec; typed webhook models and HMAC-SHA256 signature validation. (`PyGithub` is the acceptable fallback.) |
| Database | PostgreSQL 16 via `asyncpg` | Standing decisions, bypass audit, identities; hand-written SQL keeps queries auditable — no ORM. |
| Migrations | `alembic` | Plain SQL migrations applied at server start. |
| Job queue | `pgqueuer` | Postgres-backed, async-native; unique jobs by attempt ID; no extra infra (D8). |
| Anthropic SDK | `anthropic` (official) | Structured output via tool use; usage metering fields; token-count API. |
| OpenAI SDK | `openai` (official) | Structured outputs; second permitted provider. |
| Token counting | `tiktoken` (OpenAI models only) + Anthropic token-count endpoint | Pre-flight input estimation is per-provider (D7); measured usage from API responses is always authoritative. |
| Secret redaction | `detect-secrets` (as library) | Redact credentials/secrets from findings and logs (§8.11). `gitleaks` via subprocess is the stronger-detection alternative if needed. |
| Retry/resilience | `tenacity` | Provider rate-limit and transient-failure behavior per Compute Policy (§20). |
| Structured logging | `structlog` | JSON renderer; attempt ID on every record. |
| Tracing/metrics | `opentelemetry-python` | Pipeline-stage spans; provider latency/cost attributes. |
| Testing | `pytest`, `pytest-asyncio`, `hypothesis`, `testcontainers-python` | Hypothesis property tests for the gate evaluator; real Postgres in integration tests. |
| Lint/typecheck | `ruff` (lint + format) + `mypy --strict` | Pinned config; enforced in pre-commit and CI. |
| Hooks/CI | `pre-commit` + GitHub Actions | Lint, typecheck, tests on every push. |
| Release | `uv build` → PyPI (CLI), Docker image (server) | PyInstaller single-binary CLI remains a later option (§1). |

Explicit non-choices for stage one: go-git/pygit2 (merge fidelity — git CLI
only), LiteLLM or any multi-provider routing framework (multi-provider
routing is deferred by PRD §7.1, and budget metering needs native SDK usage
fields, not a normalized proxy layer), Celery/Redis/SQS/NATS (pgqueuer
suffices), an ORM (asyncpg + hand-written SQL keeps queries auditable),
a vector database (context retrieval in stage one is deterministic
path/symbol/diff based, per §8.3 — retrieval may cut cost but never scope),
and any hosted telemetry backend (opt-in only, §22).

## 4. Data model sketch (server)

`installations`, `repositories`, `change_requests` (current request key,
current Review Identity when constructed, `authoritative_attempt_id`),
`review_policies` (+`policy_versions`), `compute_policies`
(+`policy_versions`), `review_request_keys` (repo, target ref, target head,
proposed head, Review Policy version hash), `merge_candidate_identities`
(request Git fields + merge tree OID), `review_identities` (merge candidate +
Review Policy version hash), `review_attempts` (attempt ID, request key,
optional Review Identity, authority/supersession status, surface, stage
outcomes, models, usage, cost), `context_snapshots`, `dimension_runs`,
`findings` (fingerprint, severity, evidence band, grounded spans),
`gate_decisions` (Review Request Key, optional Review Identity, source Attempt
ID, state, standing flag, validity window), `bypasses` (actor, reason, bound risk snapshot, expiry), and
`audit_events` (append-only).

Making `authoritative_attempt_id` an explicit change-request field is the key
concurrency choice: completion timestamps never decide authority. Full DDL is a
follow-up design; the sketch exists to show that request keys, successful
identities, attempts, standing state, and audit are first-class rows, not log
lines.

## 5. PRD compliance checkpoints

| PRD invariant | Where enforced |
| --- | --- |
| Exact merge candidate or no review (§8.1) | D2: `git merge-tree`; conflict/missing objects → `Error`. |
| Identity-bound decisions, immediate invalidation, same-identity attempt ordering (§8.2) | D8: transactional authoritative-attempt replacement + request-attempt-identity compare-and-set at publish. |
| Context-complete, no silent degradation (§8.3, §8.4) | D3 stage outcomes + coverage disclosure in the result model. |
| Evidence before enforcement (§8.5, §13) | D6 grounded-span verification before `supported`/`verified`. |
| Policy never from reviewed repo (§8.9) | D5 path restriction (CLI) / installation-scoped storage (GitHub). |
| Read-only analysis, credential isolation (§8.11) | D2 Review Worktree materialization + env scrubbing; D11 redaction. |
| Deterministic gate (§9.5) | D4 pure evaluator. |
| Budget fail-closed (§18, §20) | D7 three-point enforcement. |
| Platform-state integrity, native override visibility (§16, §19) | D9 attempt-id fingerprints, tamper reconciliation, live permission verification for bypass. |
| CLI one-shot semantics, exit codes (§6, §19, §21.3) | D10. |
| Unchanged-identity GitHub retry (§6, §21.2) | D14 + D8 new authoritative attempt transaction. |

## 6. Risks and open questions

1. **`git merge-tree` edge cases** (octopus, submodule updates, LFS pointer
   diffs): needs an early spike with adversarial fixtures before the
   pipeline is built around it.
2. **Queue supersede semantics** for in-flight (not just queued) reviews rely on
   the publish-time request-attempt-identity compare-and-set. Integration tests must
   simulate force-push and same-identity retry during a review, including the
   older attempt completing last.
3. **Grounded-evidence verification** may reject legitimate findings whose
   evidence spans context rather than the diff; the span schema must cover
   all gathered context classes (§10), not just changed files.
4. **Provider price tables** drift; Compute Policy must version its price
   table and disclose estimate-vs-measured on every surface (§19, §20).
5. **Bypass "materially unchanged" matching** (§9.4) is the most subtle
   deterministic rule; it gets its own design doc before implementation.
6. Open: hosted vs self-hosted default distribution for the GitHub App;
   interactive bypass UX (PR comment command vs. future web UI) — comment
   command is the stage-one fallback.
7. **Re-review cost on target advance.** Every target-branch push
   invalidates all open PRs on that branch (§8.2) and forces complete
   re-reviews (§21.2). On merge-heavy days this degrades to a *merge
   convoy*: N merges produce N invalidation rounds, each costing one full
   review latency of wall-clock even though reviews within a round are
   parallel — de-facto serialized merging, the same problem merge queues
   were invented to solve. Stage-one pressure valves, in priority order:
   (a) queue coalescing (§11.1) so a PR pays only for its latest identity,
   never for superseded intermediate ones; (b) merge construction is
   millisecond-scale and token-free, so conflicting PRs reach `Error`
   without any model cost; (c) per-review budget caps (D7) bound the blast
   radius; (d) operational playbook — merge windows, off-peak merging,
   small PRs to shorten per-round latency. Two follow-up capabilities are
   recorded here for later stages:
   - *Input-identical revalidation* (supersedes an earlier "tree-identical"
     formulation, which was wrong for convoys: each merged PR enters the
     merge tree, so whole-tree OIDs almost never repeat). On invalidation,
     re-run pipeline stages 1–4 (identity, merge construction, Review Worktree,
     context gathering) — a pure function of the tree OIDs and policy
     versions, seconds-scale even for large repos, with zero model calls.
     Compare content hashes of the review's actual input set (the
     PR-introduced diff plus the gathered context set, as recorded in the
     §10 coverage disclosure) against the inputs of the reviewed attempt.
     Byte-identical inputs → the review has already been done; restore the
     prior decision. Any difference → full re-review. Soundness: the unit
     of invalidation is what the review actually read, not file paths or
     the whole tree. A change to shared/common code that the review read —
     or a newly added caller that context expansion now pulls in — changes
     the input set and forces a full re-review; changes the review never
     read cannot affect it. Constraints: context gathering must stay
     deterministic and closed before any model call (already the stage-one
     design, §3 non-choices; agentic dynamic fetching by dimensions would
     have to record every fetched item in the input set). External platform
     state (PR discussion, linked issues, external CI results) is
     snapshotted at gather time and included in the input hash, so new
     discussion triggers a re-review unless Review Policy downgrades that
     context class. This still requires a PRD amendment (§8.2 includes the
     target-head commit in identity; §7.1 defers cross-candidate reuse),
     reframed as recognition of review-equivalent input rather than reuse
     of conclusions. Strongest candidate for early promotion.
   - *GitHub Merge Queue integration*: handle `merge_group` events and
     review the merge-group candidate as the review identity. This moves
     serialization to the platform, eliminates the invalidation storm,
     and is semantically isomorphic to §8.1 (queue-prefix merge ≈ Zuul's
     speculative chain). Out of first-stage scope by design.
   A third, further-out option is relatedness-aware re-review as an
   explicit Review Policy opt-in (fail-closed default); its unsoundness
   risk is why the PRD mandates complete re-review in stage one.

## 7. Implementation adaptation checklist

The current skeleton predates parts of this clarified contract. Implementation
must converge in this order so intermediate states remain fail-closed:

1. Add an explicit `ReviewRequestKey` model and Attempt ID. Construct
   `MergeCandidateIdentity` and `ReviewIdentity` only after merge succeeds;
   construction-error reports retain the request key and use a null merge-tree
   field.
2. Change pipeline stage 1 from claiming a completed Review Identity to
   establishing the request key and Attempt. Preserve the nine externally
   reported stages while making stage 2 finalize the successful identities.
3. Add Attempt ID, request key, and optional successful identities to the
   surface-neutral report and `worktree-review.cli.result/v1`; update both human and
   JSON CLI renderers together.
4. Implemented in `worktree_review.server.state`: the GitHub
   `change_requests.authoritative_attempt_id` transaction, attempt-keyed jobs,
   and stage-9 compare-and-set. Tests cover an older same-identity Attempt
   finishing last.
5. Implemented in `worktree_review.platform.github.retry` and `webhooks`: the
   authorized GitHub retry action described by D14. Provider-call retries stay
   within one Attempt and full-pipeline reruns create new Attempts.
6. Replace archive-based Review Worktree extraction with verified raw tree/blob
   materialization. Keep product metadata outside the repository namespace and
   add adversarial tests for marker-name collisions, absolute/relative symlinks,
   `export-ignore`, `export-subst`, traversal, and unusual Git paths.
7. Make Review Policy glob matching POSIX-path exact, including leading-dot
   paths such as `.env` and `.github/**`; add coverage tests proving exclusions
   and mandatory rules cannot silently miss dotfiles.

English documents are normative. `docs/PRD.zh-CN.md` and
`docs/TECH-DESIGN.zh-CN.md` are maintained translations and must change in the
same commit whenever normative meaning changes.
