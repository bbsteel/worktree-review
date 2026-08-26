# MergeGate Technical Design — v1

- Status: First-version technical landing plan for the first-stage PRD
- Date: 2026-08-20
- Companion document: `docs/PRD.md` (normative first-stage product contract)
- Scope: architecture, language, and third-party component selection only.
  Detailed schemas, prompting algorithms, and interaction design land in
  follow-up designs.

This document resolves the decisions the PRD explicitly defers (PRD §23).
Every choice below must preserve the PRD's normative invariants: exact merge
candidate or no review, identity-bound decisions, fail-closed `Error`,
complete review or visible failure, read-only analysis, and policy that never
comes from the reviewed repository.

## 1. Language selection

### Decision: Python (single language for core, CLI, and GitHub service)

One repository, one Python package with a shared `mergegate.core`, and two
entry points:

| Entry point | Role |
| --- | --- |
| `mergegate` | Local CLI surface (PRD §4, §21.3). Distributed via PyPI (`uv tool install mergegate` / pipx). |
| `mergegate-server` | GitHub App: webhook receiver + review workers in one deployable process. Distributed as a Docker image. |

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
| Rust | Best binary story and safety, but slows iteration on prompting/analysis code that will churn heavily in stage one; LLM SDK maturity is lowest. Keep as an option if the workspace-isolation layer ever needs a native sandbox helper. |

## 2. Architecture selection

### 2.1 Top-level shape

```
┌───────────────────────────────────────────────────────────────┐
│ Surfaces (entry points of the single `mergegate` package)      │
│   mergegate          (CLI, PRD §21.3; Typer app)               │
│   mergegate-server   (GitHub App, PRD §21.2; FastAPI)          │
├───────────────────────────────────────────────────────────────┤
│ Adapters (thin; may not reinterpret product semantics, §8.12)  │
│   mergegate.platform.github  checks, comments, webhooks, authz │
│   mergegate.platform.cli     terminal report, JSON result, exit│
├───────────────────────────────────────────────────────────────┤
│ Core (platform-independent; both surfaces import this)         │
│   mergegate.core.identity    merge-candidate / review identity │
│   mergegate.core.candidate   merge construction (git merge-tree)│
│   mergegate.core.workspace   isolated read-only materialization│
│   mergegate.core.policy      Review/Compute Policy load+validate│
│   mergegate.core.context     mandatory/optional/excluded gather│
│   mergegate.core.dimension   required review dimensions        │
│   mergegate.core.provider    LLM provider abstraction + budget │
│   mergegate.core.findings    verify, dedup, classify           │
│   mergegate.core.gate        deterministic gate evaluation     │
│   mergegate.core.report      surface-neutral result model      │
│   mergegate.core.pipeline    the 9-stage pipeline (PRD §21.1)  │
├───────────────────────────────────────────────────────────────┤
│ Infrastructure                                                 │
│   system git CLI · PostgreSQL (server state) · pgqueuer jobs   │
│   LLM provider APIs · detect-secrets redaction · structlog/OTel│
└───────────────────────────────────────────────────────────────┘
```

The PRD's portability rule (§8.12) is enforced structurally: everything the
PRD calls a product semantic lives in `mergegate.core`; adapters only map
transport concepts (webhook payloads, checks API, terminal output, exit
codes) onto core types. The package uses a `src/mergegate/` layout; the CLI
and server share one distribution, with server-only dependencies behind a
`mergegate[server]` extra.

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
merge-candidate identity (§8.2). The review workspace is then materialized
with `git archive <tree> | tar -x` into a fresh directory that is chmod'd
read-only, owned by a dedicated unprivileged runtime user (server) or the
invoking user (CLI), with a scrubbed environment: no platform tokens, no
installation tokens, no provider credentials inside the worker's reachable
env (§8.11). We deliberately do **not** use go-git: merge fidelity,
rename handling, and LFS pointer behavior must match real git byte-for-byte.
The CLI requires git ≥ 2.38 and fails invocation (exit 3) otherwise.

**D3 — One shared 9-stage pipeline, explicit stage outcomes.**
`mergegate.core.pipeline` implements PRD §21.1 literally: identity → merge →
workspace → context → dimensions → verify/dedup → completeness check → gate
→ publish. Every stage writes an outcome record (`completed` / `failed` /
`not-started`) into an append-only execution record, so a fatal failure can
never be hidden by later output (§21.1) and every surface can render
per-stage completion (§19). A fatal stage failure short-circuits to `Error`;
partial findings from completed dimensions remain visible but carry the
review's `Error` state and cannot be bypassed (§16, §18).

**D4 — Deterministic, pure gate evaluator.**
`mergegate.core.gate` is a pure function
`(dimension outcomes, coverage, findings, bypasses, Review Policy) →
GateState`. No model call participates; model output may only influence
*which findings exist*, never the mapping to the decision (§9.5). The
evaluator is table-driven and property-tested (e.g., "no unresolved blocking
finding ⇒ not `Blocked`", "any incomplete required dimension ⇒ `Error`").

**D5 — Policy as versioned, content-addressed YAML under MergeGate control.**
Review Policy and Compute Policy are separate YAML documents with separate
versions (§8.2: Compute Policy changes do not invalidate standing
decisions). Each document carries a semver; its *version identity* is
`semver + SHA-256 of canonical bytes`. Storage:

- CLI: an explicitly selected path outside the reviewed repository
  (`--policy`, `--compute-policy`, or `~/.config/mergegate/`). The CLI
  refuses any policy path inside the worktree under review (§8.9).
- GitHub: per-installation rows in Postgres, edited outside the reviewed
  repo; every review records the exact policy version hashes it used.

Both load paths validate against a versioned JSON Schema and fail closed on
invalid policy. Repository files like `AGENTS.md`/`CLAUDE.md` are loaded
only as untrusted *context* (§8.10), never as policy.

**D6 — Findings via provider-constrained structured output, with grounded
evidence checks.**
Each review dimension calls the model with a JSON-Schema-constrained
response (provider-native structured outputs / tool use). The verify stage
(§21.1 step 6) is partly deterministic: every finding's supporting evidence
must reference spans (path + line range + quoted text) that actually exist
in the workspace or gathered context; ungrounded claims cannot carry
`supported` or `verified` bands (§8.5, §13). Deduplication is deterministic
fingerprinting over (path, normalized span, category, problem hash). This
keeps "self-reported model certainty is not evidence" (§13) enforceable in
code rather than in prompts.

**D7 — Budget enforcement in three points, fail-closed.**
Compute Policy carries a max per-review budget (§9.3, §20):

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
and are persisted per review attempt for audit.

**D8 — Server state in PostgreSQL; queue via pgqueuer on the same database.**
The GitHub service needs durable standing decisions, bypass audit records,
and supersede-safe scheduling. Postgres + pgqueuer (an async-native,
Postgres-backed job queue using `LISTEN`/`NOTIFY` and
`SELECT ... FOR UPDATE SKIP LOCKED`) covers both without extra
infrastructure:

- New review identity arrives → standing gate for the old identity is
  invalidated *in the same transaction* that records the new identity
  (§8.2), then a new review job is enqueued, unique-keyed by review
  identity. Superseded queued jobs are discarded; in-flight reviews check
  identity currency at publish time and refuse to publish a standing
  decision for a stale identity (§11.1 "must never leave the previous gate
  decision standing").
- No Redis/SQS/NATS/Celery in stage one.

The CLI is stateless except an optional local cache directory
(`~/.cache/mergegate/`) for immutable artifacts keyed by content hash;
caching may never reduce review scope or reuse conclusions (§11.1).

**D9 — Append-only audit events, with published-state self-audit.**
Bypass records, gate transitions, invalidations, policy versions, model
provenance, and cost data are written as append-only audit events
(§8.2, §16). Bypass binds to review identity + finding fingerprint + stated
risk snapshot (problem statement, severity, impact, key evidence); expiry on
identity or Review-Policy change and "materially unchanged" re-match on
re-review are evaluated deterministically from these fields (§16, §9.4).

MergeGate does not trust the platform-visible standing state it published;
it reconciles it against its own records (the forged-status lesson from
palantir/policy-bot):

- Every published check embeds an *attempt-id fingerprint* (a short hash of
  the review attempt id) in its output, and its details URL resolves to our
  server-rendered view of the database decision. A status or check forged by
  someone with repository write access cannot reproduce the current
  fingerprint.
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
  machine-readable schema `mergegate.cli.result/v1` (§19).
- Exit codes: `0` = `Passed`, `1` = `Blocked`, `2` = `Error`,
  `3` = invalid invocation (dirty worktree, unresolvable refs, policy inside
  repo, git too old, bad flags). `Passed with bypass` is never produced by
  the CLI (§4, §11).
- Before any remote transmission, the CLI prints provider, model, data
  destination, and known retention behavior, and requires that transmission
  to be explicitly permitted in trusted Compute Policy (§8.11). No feedback
  or telemetry leaves the CLI without explicit opt-in (§22).

**D11 — Untrusted-content and secret hygiene.**
All repository content is data (§8.10): context assembly inserts it as
quoted, delimited model input; reviewer tools and permissions come only from
trusted policy (§8.11). Findings and logs pass through a detect-secrets-based
redaction step before publication (§8.11).

**D12 — Deployment for stage one.**
The server ships as a single Docker image running `mergegate-server`
(webhook HTTP + embedded pgqueuer workers) beside a Postgres instance; the
CLI ships via PyPI and installs with `uv tool install mergegate` or pipx.
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

## 3. Third-party component selection

| Concern | Choice | Why / notes |
| --- | --- | --- |
| Language toolchain | Python ≥ 3.12, `uv` for env/lock/publish | See §1. `uv` covers venvs, lockfile, build, and PyPI upload. |
| Packaging/build | `hatchling` (via uv), `src/mergegate/` layout | Single package; server-only deps behind the `mergegate[server]` extra; two console entry points. |
| CLI framework | `typer` | Type-hint-driven commands on top of Click; exit-code control stays ours. |
| HTTP server | `fastapi` + `uvicorn` | Webhook receiver; async-native; OpenAPI for the details/health endpoints. |
| HTTP client | `httpx` (async) | Provider SDKs and GitHub calls share one async client discipline. |
| YAML parsing | `pyyaml` | Policy documents; version hash computed over the canonicalized parsed form, not raw bytes. |
| Schema/validation | `pydantic` v2 + `jsonschema` | JSON Schema is the single source of truth for policy and result formats; Python types generated from schemas; fail-closed on invalid input. |
| Git operations | system `git` CLI ≥ 2.38 via `asyncio` subprocess | `merge-tree --write-tree`, `archive`, ref resolution. Exactness beats embedding (D2). |
| GitHub API + webhooks | `githubkit` | Async, generated from GitHub's OpenAPI spec; typed webhook models and HMAC-SHA256 signature validation. (`PyGithub` is the acceptable fallback.) |
| Database | PostgreSQL 16 via `asyncpg` | Standing decisions, bypass audit, identities; hand-written SQL keeps queries auditable — no ORM. |
| Migrations | `alembic` | Plain SQL migrations applied at server start. |
| Job queue | `pgqueuer` | Postgres-backed, async-native; unique jobs by review identity; no extra infra (D8). |
| Anthropic SDK | `anthropic` (official) | Structured output via tool use; usage metering fields; token-count API. |
| OpenAI SDK | `openai` (official) | Structured outputs; second permitted provider. |
| Token counting | `tiktoken` (OpenAI models only) + Anthropic token-count endpoint | Pre-flight budget estimation is per-provider (D7); measured usage from API responses is always authoritative. |
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

`installations`, `repositories`, `review_policies` (+`policy_versions`),
`compute_policies` (+`policy_versions`), `review_identities` (repo, target
ref, target head, proposed head, merge tree OID, policy version hash),
`review_attempts` (attempt ID, surface, stage outcomes, models, usage,
cost), `dimension_runs`, `findings` (fingerprint, severity, evidence band,
grounded spans), `gate_decisions` (state, standing flag, validity window),
`bypasses` (actor, reason, bound risk snapshot, expiry), `audit_events`
(append-only). Full DDL is a follow-up design; the sketch exists to show
that identity, standing state, and audit are first-class rows, not log
lines.

## 5. PRD compliance checkpoints

| PRD invariant | Where enforced |
| --- | --- |
| Exact merge candidate or no review (§8.1) | D2: `git merge-tree`; conflict/missing objects → `Error`. |
| Identity-bound decisions, immediate invalidation (§8.2) | D8: transactional invalidation + identity-currency check at publish. |
| Context-complete, no silent degradation (§8.3, §8.4) | D3 stage outcomes + coverage disclosure in the result model. |
| Evidence before enforcement (§8.5, §13) | D6 grounded-span verification before `supported`/`verified`. |
| Policy never from reviewed repo (§8.9) | D5 path restriction (CLI) / installation-scoped storage (GitHub). |
| Read-only analysis, credential isolation (§8.11) | D2 workspace materialization + env scrubbing; D11 redaction. |
| Deterministic gate (§9.5) | D4 pure evaluator. |
| Budget fail-closed (§18, §20) | D7 three-point enforcement. |
| Platform-state integrity, native override visibility (§16, §19) | D9 attempt-id fingerprints, tamper reconciliation, live permission verification for bypass. |
| CLI one-shot semantics, exit codes (§13, §19, §21.3) | D10. |

## 6. Risks and open questions

1. **`git merge-tree` edge cases** (octopus, submodule updates, LFS pointer
   diffs): needs an early spike with adversarial fixtures before the
   pipeline is built around it.
2. **Queue supersede semantics** for in-flight (not just queued) reviews
   rely on the publish-time identity check; race windows must be covered by
   integration tests simulating force-push during a review.
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
     re-run pipeline stages 1–4 (identity, merge construction, workspace,
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
