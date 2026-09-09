# Worktree Review Product Requirements Document

- Status: First-stage product contract ready for technical design
- Date: 2026-08-27
- Visibility: Public product document
- Product form: Worktree-based code review with a first-stage GitHub merge gate and local CLI
- Chinese translation: `docs/PRD.zh-CN.md`

This is a living description of the intended product direction, not a delivery
commitment. The first-stage requirements are normative for the initial product;
later-stage capabilities remain directional until promoted into that scope.

## Terminology and conceptual model

The following terms separate the object being reviewed, the information used to
review it, an execution of that review, and the decision currently allowed to
gate a platform change request:

| Term | Definition |
| --- | --- |
| Worktree Review | A review method that evaluates a proposed change in a complete, isolated materialization of the resulting repository tree. The diff locates the change; the full tree supplies the context needed to understand and verify it. The method does not require the materialization to be created by `git worktree add`. |
| Review Worktree | The immutable filesystem view materialized for one successfully constructed merge candidate. It is a product-level review environment, not necessarily a Git linked worktree. |
| Review Request Key | The pre-construction key consisting of source repository, target ref, resolved target-head commit, proposed-head commit or immutable worktree snapshot commit, and Review Policy version. It identifies what Worktree Review was asked to construct and review even when merge construction fails. |
| Merge Candidate Identity | The source repository, target ref, resolved target-head commit, proposed-head commit, and resulting merge-tree identifier. It exists only after merge construction succeeds. |
| Review Identity | The Merge Candidate Identity plus the applied Review Policy version. It defines exactly what a completed review conclusion applies to. |
| Review Context | The code, diff, tests, documentation, change-request metadata, external results, and other evidence gathered for one Attempt. Context informs a review but is not its identity. |
| Review Attempt | One execution started from a Review Request Key. It has an Attempt ID and records its surface, Compute Policy version, model provenance, context snapshot, stage outcomes, usage, and cost. A successful construction also binds the Attempt to a Review Identity. |
| Authoritative Attempt | The latest Attempt that a platform integration designates as eligible to publish the Standing Decision for its current Review Request. Older Attempts are superseded even when they have the same Review Identity. |
| Standing Decision | The currently effective platform gate result. It is derived only from the Authoritative Attempt and is always bound to the current Review Request Key; after construction succeeds it is also bound to Review Identity. This permits a construction `Error` to stand without inventing a merge candidate. |
| Review Result | The immutable output of one Attempt. A CLI result is one-shot and never becomes a remote Standing Decision. |

In short: Review Identity says *what a conclusion applies to*; Review Context
says *what information an attempt used*; Review Attempt says *which execution
produced a result*; and Standing Decision says *which result currently has gate
authority*.

## 1. Product summary

Worktree Review is a platform-independent, policy-driven AI code-change review
product. Instead of treating a diff as the complete review object, it reviews the
exact resulting tree in an isolated Review Worktree, publishes evidence-backed
findings, and decides whether that merge candidate may pass under user-owned
review and compute policies.

Worktree Review provides an open, user-controlled alternative for code-change review
and merge gating. Its long-term direction gives users control over review
standards, language, models, budgets, quotas, and routing.
GitHub is the first repository-platform integration, not the boundary of the
product. A local CLI exposes the same review semantics without requiring a pull
request. The first product stage deliberately implements a smaller, fail-closed
subset of this direction.

Reliable merge gating is the original motivation for the product and the
highest-priority first-stage outcome. Worktree Review is the product and review
method; the GitHub Gate is its first authoritative enforcement surface, not a
separate compliance-only product.

## 2. Problem statement

Independent developers and small open-source repositories can encounter
limitations in AI-assisted review workflows:

- Automatic-review eligibility may vary by repository or service plan.
- Reviews may stop or require manual triggering after configured usage
  thresholds are reached.
- Review language and severity presentation may not match the user's needs.
- Users cannot fully control which models are used, how quota is consumed, or
  how providers are switched.
- Generic review prompts do not preserve an experienced reviewer's standards in
  a reusable, testable form.
- Diff-only reviews can miss behavior visible only through callers, callees,
  tests, configuration, documentation, and business requirements.
- A review bot may publish comments without providing a dependable merge
  decision.

Worktree Review addresses these problems by making review policy, compute policy,
merge-candidate context, evidence strength, review coverage, and the gate
decision first-class product concepts.

## 3. Product vision

Every eligible merge candidate should receive a context-complete review under
rules the policy owner controls. The result must say what was reviewed, what
was found, how strong the evidence is, what the review cost, and whether the
merge gate is open.

The product promise is:

> Review the worktree, not just the diff. Control the gate with evidence.

## 4. Product form and platform scope

Worktree Review has one platform-independent product contract exposed through multiple
surfaces:

| Surface | First-stage role | Result authority |
| --- | --- | --- |
| GitHub integration | Automatically reviews eligible pull requests, publishes inline findings and a durable check, and supports auditable finding bypass. | A standing gate decision bound to the current review identity. |
| Local CLI | Reviews a selected local merge candidate on demand, including the current worktree snapshot, and emits human-readable and machine-readable results. | A one-shot result and process exit status for the reviewed identity; it does not create or change a remote standing gate. |
| Other repository platforms | Later integrations map native change requests, checks, comments, and authorization onto the same Worktree Review semantics. | Must preserve the same identity, evidence, coverage, and fail-closed rules. |

GitHub-specific triggers, presentation, and authorization may differ from those
of a future platform. They must not redefine Review Policy, evidence bands,
coverage completeness, finding meaning, or gate-state evaluation. The CLI and
all platform integrations use the same semantic review contract.

## 5. Target users

### 5.1 First-stage user

An experienced individual developer or small-project maintainer who:

- Maintains code in Git, initially in a public GitHub repository or a local
  workspace.
- Uses coding agents and wants both pull-request gating and local checks before
  publishing changes.
- Reviews their own branches and branches created by trusted collaborators.
- Has substantial code-review experience they want to reuse.
- Wants well-supported findings rather than high comment volume.
- Wants to configure review language, severity, evidence, and blocking behavior.
- Wants explicit control over the selected model and per-review cost.

### 5.2 Later users

- Open-source maintainers reviewing pull requests from external forks.
- Maintainers using private-repository platform integrations.
- Small engineering teams sharing policies across repositories.
- Organizations that need auditable, repository-owned merge policies.
- Users of repository and code-review platforms other than GitHub.

## 6. First-stage scope and requirements

The first product stage supports two entry points:

- Ready-for-review pull requests whose head branch belongs to the same public
  GitHub repository as the target branch.
- On-demand CLI review of the current local worktree snapshot against a target
  ref. The target defaults to `HEAD`, may be selected explicitly, or may be
  expressed as the last N commits from `HEAD`; an explicit committed proposed
  ref remains available. The CLI captures tracked and non-ignored untracked
  files into an immutable Git snapshot before construction.

The GitHub entry point, including authoritative invalidation, retry, publication,
and merge blocking, has delivery priority over convenience features on either
surface. The CLI remains a first-stage surface because it exercises and exposes
the same review and deterministic gate semantics locally.

Each distinct review identity receives a complete Standard Review. Both entry
points construct and review the same kind of merge candidate, apply the same
Review Policy and gate evaluation, and expose the exact identity reviewed. The
first stage does not reuse review conclusions incrementally across candidates.

Worktree Review must:

1. Automatically review an eligible GitHub pull request when it is opened,
   reopened, marked ready for review, or updated.
2. Let a user start the same review locally through the CLI. By default it
   reviews current worktree changes against `HEAD`; the user may select a target
   ref, review the last N commits plus current changes, or select a committed
   proposed ref explicitly.
3. Review the merge candidate produced by merging the proposed head into the
   resolved target head, rather than reviewing the proposed head alone.
4. Bind every attempt and result to its review request key. After merge
   construction succeeds, also bind it to the resulting merge candidate and
   Review Identity. A construction failure reports the merge-tree identifier as
   unavailable rather than claiming that a merge candidate exists; a platform
   change-request identifier is additional provenance when one exists.
5. Immediately invalidate a standing platform gate when any part of its review
   request key changes; invalidation happens before a replacement attempt starts.
   Starting another attempt for the same key also withdraws the prior standing
   decision until the new authoritative attempt completes.
6. Prepare a complete, isolated, read-only Review Worktree for the exact merge
   candidate without executing code supplied by the proposed change.
7. Gather relevant code and business context according to explicit mandatory,
   optional, excluded, and unreviewable-context rules.
8. Complete every review dimension required by Review Policy, expose the outcome
   of each dimension, and produce `Error` if any required dimension does not
   complete.
9. Publish findings with severity, evidence strength, impact, supporting
   evidence, and provenance; GitHub presents eligible findings inline, while the
   CLI reports them against local paths and lines.
10. Support `critical`, `major`, `minor`, and `suggestion` findings.
11. Produce an explicit `Passed`, `Passed with bypass`, `Blocked`, or `Error`
    result after review starts. `Passed with bypass` is available only on a
    surface that provides durable authorization and audit records.
12. Allow authorized GitHub users to bypass a blocking finding from a completed
    review for the current review identity, with an auditable reason.
13. Let an authorized GitHub user explicitly retry the current unchanged review
    request after an `Error` or when changed Compute Policy should be applied.
    The retry creates a new authoritative attempt without changing Review
    Identity semantics.
14. Give the CLI stable, documented process exit behavior, with success for
    `Passed` and distinct nonzero outcomes for `Blocked`, `Error`, and invalid
    invocation.
15. Offer repair guidance without modifying the proposed change.
16. Let users encode and version their review experience as policy stored outside
    the repository under review.
17. Let users select the permitted provider and model and apply a safe hard
    output-token limit per provider call; advanced users may set a per-review
    budget and token prices.
18. Fail explicitly when a complete review cannot finish, including when the
    merge candidate cannot be constructed or the budget is exhausted.
19. Make the review request key, attempt identifier, merge-candidate and Review
    identities when available, policy versions, model usage, cost, coverage, and
    failure behavior visible on every surface.
20. Ship an inspectable, product-owned prompt hierarchy for every review
    dimension. The hierarchy must keep product scope, safety boundaries, evidence
    requirements, dimension focus, and structured-output requirements in ordered
    layers that are never loaded from the reviewed repository.

## 7. First-stage boundaries

### 7.1 Deferred product capabilities

The following capabilities remain part of the product direction but are not
requirements for the first product stage:

- Reviews of pull requests from external forks.
- Hosted reviews of private repositories.
- Integrations with repository platforms other than GitHub.
- Incremental reuse of review conclusions across merge candidates.
- Finding identity and lifecycle across merge candidates.
- Interactive reassessment of findings from pull-request discussion alone.
- Manually triggered Deep Review.
- Multi-provider routing, quota-aware fallback, and time-based scheduling.
- Calibrated numerical confidence thresholds.

If Deep Review is introduced later, its result applies only to the exact review
identity on which it ran. A later merge candidate returns to Standard Review
unless Review Policy explicitly requires Deep Review for that new identity.

### 7.2 Non-goals

Worktree Review is not intended to be:

- A general-purpose coding agent.
- An IDE completion or editing extension.
- An autonomous code-fixing system.
- A hosted replacement for every linter or SAST product.
- A Jira, Linear, or Slack workflow platform.
- A team analytics and management dashboard.
- An automatic reviewer assignment service.
- A unit-test generation service.
- A merge-conflict resolution service.
- A repository modification or auto-commit service.

Worktree Review may provide a suggested fix or illustrative patch, but it does not
apply, commit, or push that fix in the first stage.

## 8. Product principles

### 8.1 Exact merge candidate or no review

The review subject is the result of merging a committed proposed head or an
immutable invocation-captured worktree snapshot into a resolved target head.
The target head is not the historical merge-base. GitHub resolves these commits
from the current pull request; the CLI resolves its target and captures its
proposed snapshot once at invocation time. If either resolved commit changes, a
new merge candidate exists.

If Worktree Review cannot construct the merge candidate, including because of a merge
conflict, the review ends with `Error`. A head-only worktree has no gate value and
must not produce a passing decision.

### 8.2 Decisions are identity-bound

Worktree Review applies the terminology above as follows:

- The review request key exists before merge construction and remains available
  when construction fails. It is the scheduling, failure-reporting, and audit key
  for that case; it must not be presented as a successfully constructed Review
  Identity.
- Merge candidate identity and Review Identity exist only after construction
  produces a resulting merge-tree identifier. A platform change-request
  identifier is provenance, not a substitute for these Git identities.
- Finding identity: a finding within one review identity.
- Bypass identity: the review identity, finding identity, and the stated risk
  that the authorized user chose to bypass.

Every execution is a Review Attempt. Its invoking surface, Compute Policy
version, selected model provenance, context snapshot, stage outcomes, usage,
cost, and attempt identifier are execution provenance. They do not change what
Review Identity means.

A standing platform gate decision is valid only for its authoritative attempt
and review request key and, after successful construction, its Review Identity.
A target-ref change, target-head change, proposed-head change, retarget, or
applicable Review Policy change invalidates the old decision immediately and
starts a new authoritative attempt. Starting an explicit retry for an unchanged
review request key also designates a new authoritative attempt and withdraws the
prior standing decision until that attempt finishes.

At most one attempt is authoritative for a platform change request at a time.
Every older queued or in-flight attempt is superseded, including an older attempt
with the same Review Identity. A superseded attempt may finish and retain an
immutable audit result, but it must not publish, restore, or overwrite the
standing decision. Publication must atomically confirm the current review
request key and authoritative attempt identifier, plus Review Identity whenever
construction succeeded.

A CLI invocation creates an independent one-shot attempt. Its result applies to
the review request key and, when construction succeeds, the exact Review
Identity printed in its output. It is never a standing decision for later local
state.

A Compute Policy change can change what a later review discovers, but it does not
change the meaning of Review Policy. It does not silently invalidate a completed
decision. Applying changed Compute Policy to an existing GitHub review requires
an authorized explicit retry, which creates a new authoritative attempt and
withdraws that decision until the attempt completes. Provider-level retries
inside one attempt do not create another Review Attempt; rerunning the complete
review pipeline does.

### 8.3 Context-complete by default

Standard Review must use all relevant context required by Review Policy. Lower
latency or cost may be achieved through retrieval, caching, or model choice, but
not by reducing the required review scope.

### 8.4 No silent degradation

Worktree Review must never represent a partial or failed review as a successful
review. Skipped files, missing context, exhausted budget, provider failure, and
incomplete coverage must be visible.

### 8.5 Evidence before enforcement

A model statement is not itself a gate decision. Blocking findings require the
minimum evidence band configured by Review Policy.

### 8.6 User-owned policy

Policy owners control what is reviewed, what severity means, which evidence is
sufficient, which findings block, and who may bypass on surfaces that support
durable bypass.

### 8.7 User-owned compute

Policy owners control the permitted provider and model in the normal first-stage
path. That path uses a safe hard output-token limit for each provider call and
the provider account controls actual spend. Advanced Compute Policy may add a
per-review budget, token prices, and uncertain-price behavior. Later compute
policies may add routing, quotas, scheduling, and fallback without changing
Review Policy semantics.

### 8.8 Bypass is not resolution

A bypass records that an authorized user chose to proceed despite the stated
risk. It must not be displayed as if Worktree Review withdrew the finding or
determined that the code was safe.

### 8.9 Policy never comes from the reviewed repository

Review Policy and Compute Policy are stored under Worktree Review's control and are
never loaded from the Git refs or merge tree under review. GitHub uses policy held
by its Worktree Review installation. The CLI uses its product-owned built-in Review
Policy when no custom policy is supplied; any custom Review Policy or Compute Policy
must come from an explicitly selected trusted location outside the reviewed
repository. A proposed change can therefore never modify the rules that gate it.
Repository instruction files such as `AGENTS.md` and `CLAUDE.md` are review
context, not policy.

### 8.10 Repository content is data, not instructions

Everything under review, including code, comments, linked issues, change-request
discussion, and participant-supplied evidence, is untrusted input. It may inform
findings, but it must never override policy or control reviewer tools.

### 8.11 First-stage analysis is read-only

The first stage retrieves files and performs model analysis but does not execute
proposed-change code, tests, build scripts, hooks, or binaries. The Review
Worktree cannot access platform credentials, installation tokens, or
model-provider credentials. Tool, file-system, and network permissions come only
from trusted product policy or an explicitly selected local provider command;
that command is never loaded from the reviewed repository and is not interpreted
through a shell. Findings and logs must redact complete credentials and other
detected secrets.

Before a CLI review hands repository content to a remote model provider or a
configured local command, it must identify the provider, model, data destination,
known retention behavior, and (for a local command) a safe configuration
fingerprint. It must require explicit trusted configuration that permits the
handoff. A local executable is not evidence that inference, network transmission,
or data retention is local; the disclosure must say that content is handed to the
configured command and that downstream behavior is outside Worktree Review's
knowledge.

### 8.12 Product semantics are portable

The GitHub integration and local CLI share merge-candidate construction, Review
Policy, Compute Policy, evidence bands, coverage rules, finding structure, and
gate evaluation. A platform adapter may map these concepts to native checks,
comments, permissions, and events, but it must not weaken or reinterpret them.

## 9. Core concepts

### 9.1 Review Worktree

Every execution of a review uses an isolated, complete, read-only Review
Worktree containing the exact merge result for its merge candidate identity. The
Review Worktree records both parent commits and the resulting tree or merge
commit used for review.

The product requires Review Worktree isolation, revision traceability, and
protection from superseded reviews. The construction and storage mechanisms are
deferred to technical design.

### 9.2 Review Policy

A Review Policy captures the user's review experience and governs:

- Finding categories and priorities.
- Required review dimensions and their completion requirements.
- Severity definitions.
- Evidence-band requirements.
- Blocking behavior.
- Mandatory, optional, excluded, and unreviewable context.
- Path-, language-, and component-specific rules.
- Positive examples, negative examples, and accepted exceptions.
- Comment presentation and output language.
- Bypass authorization and requirements.

Review Policy must be reusable and versionable. It is stored under Worktree Review's
control, never in the reviewed repository. Its storage format and evaluation
mechanism are deferred.

### 9.3 Compute Policy

For the first product stage, Compute Policy governs:

- The permitted provider and model for a review.
- The maximum output tokens for each provider call.
- An optional per-review budget, token prices, and uncertain-price behavior for
  advanced deployments.
- Provider availability and rate-limit behavior.
- The treatment of measured, declared, and estimated usage and cost.

Changing Compute Policy may change the findings produced by a later review. It
must not change severity or evidence-band definitions, blocking rules, or any
other Review Policy meaning.

### 9.4 Finding

A finding is a structured claim about a merge-candidate change. It includes at
least:

- Location and affected code.
- Category.
- Severity.
- Evidence band.
- Problem statement.
- Expected impact.
- Supporting evidence.
- Relevant policy rule, when applicable.
- Suggested repair direction, when useful.
- Review identity and execution provenance.

A finding is scoped to one review identity in the first product stage. Worktree Review
does not promise to preserve finding identity across merge candidates. When the
same review identity is reviewed again, Worktree Review may recognize a materially
unchanged finding so that an applicable bypass remains auditable, but it must not
transfer a bypass to a materially different risk.

### 9.5 Gate decision

The gate decision is a deterministic policy evaluation over required-dimension
completion, completed review coverage, and unresolved findings. It is not a raw
model response. Model analysis may change which findings exist; the mapping from
dimension completion, coverage, finding severity, evidence band, and bypass
state to the gate decision must not vary by model.

### 9.6 Product-owned prompt hierarchy

Every review dimension uses an ordered prompt hierarchy owned by Worktree Review:

1. Product role and exact merge-candidate scope.
2. Untrusted-content and tool-safety boundary.
3. Evidence and provenance requirements.
4. The selected dimension's focus.
5. Structured findings output requirements.

The layers are inspectable product resources and are never read from the reviewed
repository. They are prompt inputs, not Review Policy, and cannot grant a provider
authority to mark a finding `verified`.

## 10. Review scope and context

Standard Review may use all relevant context available through the invoking
surface and within first-stage scope, including:

- Change-request title and description when a platform integration supplies them.
- Linked public issues and acceptance criteria when available.
- The complete merge-candidate diff and changed files.
- Callers, callees, public interfaces, data structures, and dependencies.
- Relevant tests and test intent, without executing the tests.
- Review Policy stored under Worktree Review's control.
- Repository instruction files such as `AGENTS.md` and `CLAUDE.md`, treated as
  untrusted context.
- Relevant architecture, product, and business documentation in the reviewed
  repository.
- Existing change-request discussion when available.
- The resolved target implementation represented in the merge candidate.
- Relevant commit history.
- Available results from CI, tests, linters, and security checks run outside the
  Review Worktree.

Review Policy classifies context as follows:

| Context class | Product behavior when unavailable or unreadable |
| --- | --- |
| Mandatory | The review ends with `Error`. |
| Optional | The review may complete, but the missing context is disclosed in coverage. |
| Explicitly excluded | The content is outside policy scope and is disclosed as excluded. |
| Unreviewable changed content | Review Policy must explicitly exclude it; otherwise the review ends with `Error`. |

Unreviewable content may include binaries, unavailable Git LFS objects, or files
that exceed supported limits. Worktree Review must not silently skip such content and
claim complete coverage.

Context completeness means complete coverage of the scope required by the
applied Review Policy, not possession of all possible knowledge. Missing evidence
for one suspected issue must not be promoted into a blocking finding; missing
mandatory context for the review instead produces `Error`.

## 11. Review mode

### 11.1 Standard Review

Standard Review is the only first-stage review mode. It:

- Starts automatically for every new review request key of an eligible GitHub
  pull request, for every authorized explicit retry, and on demand for each CLI
  invocation.
- Covers all changed content unless Review Policy explicitly excludes it.
- Uses all mandatory context and any available relevant optional context.
- Completes every review dimension required by Review Policy and reports whether
  each one completed, failed, or could not start because of an earlier fatal
  error.
- Supports policy-defined review dimensions such as correctness, security,
  performance, architecture, maintainability, and style.
- Performs a complete review for every merge candidate.
- Produces one gate decision for the exact review identity.

Required review dimensions may execute concurrently, but concurrency is an
implementation choice. A review is complete only after every required dimension
completes. If any required dimension fails or does not start, the result is
`Error`; findings from completed dimensions may remain visible as partial output.

The first product stage does not incrementally reuse review conclusions from a
previous merge candidate. Retrieval and immutable artifact caches may be reused
only when doing so does not reduce review scope or preserve stale conclusions.

When a GitHub identity change or explicit retry occurs while an attempt is queued
or in flight, the old standing decision becomes invalid immediately and the new
attempt becomes authoritative. Implementations may cancel or coalesce superseded
work for cost control. If an older attempt cannot be stopped, its result remains
audit-only and must fail the atomic authority check at publication even when it
has the same Review Identity as the newer attempt.

The CLI resolves its target once and captures its proposed source once at
invocation time. A committed proposed ref is used directly; otherwise the
current worktree (tracked and non-ignored untracked files) is captured as an
immutable Git snapshot, while a clean worktree resolves to the current `HEAD`.
The CLI reports the resolved identities and never implies that its result covers
commits or working-tree changes created after that capture.

Draft pull requests are not eligible for review. Marking a pull request ready
starts review; converting it back to draft invalidates any standing Worktree Review
decision. Pull requests from external forks are reported as unsupported in the
first stage rather than receiving a partial review experience.

## 12. Severity model

| Severity | Product meaning | Default gate behavior |
| --- | --- | --- |
| `critical` | Exploitable compromise, authorization bypass, credential exposure, certain data loss, or a clear severe production-failure path. | Block when evidence is sufficient. |
| `major` | A real functional defect, material regression, important compatibility break, concurrency or transaction error, or significant performance failure. | Block when evidence is sufficient. |
| `minor` | A limited edge case or concrete maintainability, correctness, or performance issue with restricted impact. | Non-blocking. |
| `suggestion` | An optional improvement, alternative design, naming improvement, style preference, or nonessential refactor. | Non-blocking. |

Review Policy may change blocking behavior. By default, unresolved `critical`
and `major` findings with at least `supported` evidence block.

## 13. Evidence strength and confidence

Evidence strength is the policy input used to determine whether a finding can
block:

| Evidence band | Meaning | Enforcement eligibility |
| --- | --- | --- |
| `insufficient` | The concern is a hypothesis without enough supporting evidence. | Never blocks. |
| `supported` | Available context demonstrates a concrete violated contract, reachable failure path, or equivalent repository-grounded basis. | May block under Review Policy. |
| `verified` | The issue is reproducible, logically necessary, or independently confirmed as required by policy. | May block under Review Policy. |

Evidence may include:

- A reachable execution or data path.
- A violated contract or acceptance criterion.
- A caller/callee mismatch.
- A reproducible or logically necessary failure condition.
- A conflicting test, type, configuration, or established repository pattern.
- Independent confirmation when policy requires it.

Every evidence span carries a typed evidence source (for example
`review-worktree`, `target-tree`, `merge-diff`, or `metadata`), an immutable
snapshot identity, and, when applicable, the path's change kind. Verification
may ground a span only against the declared source and matching snapshot;
`context_class` describes the context presentation and is not evidence
provenance. A quote found in another source, such as a deleted target-tree
file, does not ground a span declared against the Review Worktree.

The first-stage verifier derives the enforcement band locally. Grounded spans
provide at most the basis for `supported`; a provider's self-reported band can
never establish `verified`. `verified` requires independent trusted
verification provenance recorded outside the provider finding, so the
first-stage pipeline caps provider-produced findings at `supported` unless a
later verifier supplies that provenance. Fingerprints are also recomputed
locally, including a sentinel path for findings with no valid span; provider
fingerprints are never used for deduplication.

Self-reported model certainty is not evidence. Review Policy defines the minimum
evidence band required for blocking, and that definition remains stable across
models.

Worktree Review may display a numerical or human-readable confidence diagnostic when
useful, but the first product stage must identify its model provenance and must
not use it as a blocking threshold or imply that values from uncalibrated models
are comparable.

## 14. Gate states

| Gate state | Meaning |
| --- | --- |
| `Awaiting review` | A platform integration has an eligible review identity with no standing decision and no active review yet. |
| `In progress` | A complete review for the current review identity is active. |
| `Passed` | Every required review dimension and required coverage completed, with no unresolved blocking findings. |
| `Passed with bypass` | Every required review dimension and required coverage completed; all remaining blocking findings have applicable authorized bypasses. |
| `Blocked` | Every required review dimension and required coverage completed, and one or more unresolved, non-bypassed blocking findings remain. |
| `Error` | Worktree Review could not complete every required review dimension, required coverage, or a valid gate decision. |

`Error` is fail-closed. Finding bypass is unavailable for an incomplete review,
and no product action converts `Error` to `Passed with bypass`. The only product
path out of `Error` is to correct or change the blocking condition and rerun the
review successfully. A platform administrator may use a platform-native
administrative bypass when one exists, but Worktree Review keeps its state as `Error`
and records no passing decision. The CLI returns its documented nonzero `Error`
outcome.

When a platform review request changes or an unchanged request is explicitly
retried, the prior state ceases to be the standing gate before the authoritative
replacement attempt begins. A new identity never inherits `Passed`, `Passed with
bypass`, or a finding bypass from the previous identity. A same-identity retry
may retain an applicable finding bypass under §16, but it does not inherit the
prior standing decision. CLI invocations do not inherit a gate or bypass from
prior invocations.

An unresolved blocking finding is one whose severity and evidence band block
under the current Review Policy and which has not received an applicable finding
bypass.

## 15. Finding disposition and feedback

When an invoking surface supports feedback, review participants may label a
finding as:

- `confirmed`: The participant agrees that it is a real problem.
- `false positive`: The participant believes the finding is not valid.
- `uncertain`: The participant cannot determine whether it is valid.
- `accepted risk`: The participant accepts proceeding despite the stated risk.

These labels are participant feedback, not system ground truth, and do not by
themselves change the gate. `accepted risk` is not a bypass unless an authorized
user performs the separate bypass action and supplies its required reason.

In the first product stage, discussion evidence does not automatically withdraw,
downgrade, or retain a finding. A code change creates a new merge candidate and
therefore a new complete review. Interactive evidence-based reassessment without
a code change is a later-stage capability.

## 16. Finding bypass

In the first stage, an authorized GitHub user may bypass a blocking finding only
after a complete review. A future platform may expose the same action only if it
can provide equivalent durable authorization and audit records. Bypass behavior
must:

- Require an explicit reason.
- Record the actor, time, source repository, platform change request when one
  exists, review identity, execution provenance, and affected finding.
- Bind to the finding's problem statement, severity, expected impact, and key
  evidence at the time of acceptance.
- Remain applicable when the same review identity is reviewed again only when
  the stated risk is materially unchanged.
- Require renewed confirmation if the severity, problem substance, expected
  impact, or key evidence changes materially.
- Expire when the merge candidate or applicable Review Policy version changes.
- Preserve enforcement for unrelated and newly discovered findings.
- Remain visibly distinct from resolution or withdrawal; bypassed findings stay
  visible.
- Coexist with GitHub's native administrative bypass capabilities.

The authorization model should align with GitHub's `write`, `maintain`, and
`admin` repository roles and allow Review Policy to impose stricter rules. Exact
authorization mapping is deferred.

A finding from a partial or failed review cannot be bypassed because `Error`
represents unknown review risk, not only the findings already discovered.

## 17. Repair suggestions

Worktree Review may provide:

- A repair direction.
- An illustrative code snippet or patch.
- Recommended tests.
- Relevant examples from the repository.

Worktree Review does not apply, commit, or push the repair in the first stage. A
suggested repair is not verified until the author creates a new merge candidate
and Worktree Review completes its review.

## 18. Budget exhaustion and incomplete review

If an advanced configured dollar budget cannot cover a complete review:

- The gate state is `Error`.
- Worktree Review reports that the budget was exhausted.
- Completed, excluded, optional-missing, and unreviewed scope is visible.
- Findings already discovered may remain visible but cannot be bypassed.
- No `Passed` or `Passed with bypass` decision is produced.
- The user may change Compute Policy and start a new attempt for the same review
  request and Review Identity when merge construction remains unchanged.

The same fail-closed behavior applies to provider failure, an incomplete required
review dimension, unavailable mandatory context, unreviewable in-scope content,
missing Review Worktree, merge conflict, or any other condition that prevents a
complete review. Successfully completing a later review supersedes `Error`;
changing Compute Policy alone does not.

## 19. Output and localization

The user can configure the review output language. Localization applies to
explanations and interaction while preserving source identifiers, API names,
code, and exact error messages where translation would reduce precision.

Every surface presents:

- Findings tied to source paths and lines when available.
- Severity and evidence band.
- Optional model-specific confidence diagnostics.
- Supporting evidence and expected impact.
- Suggested repairs when appropriate.
- A review summary.
- Gate state.
- Review request key and attempt identifier.
- Merge-candidate and Review Identity when construction succeeds; otherwise an
  explicit unavailable merge-tree identifier and construction failure.
- Completion or failure status for candidate construction, Review Worktree
  preparation, context gathering, every review dimension required by Review
  Policy, and gate evaluation.
- Mandatory, optional-missing, excluded, unreviewable, and reviewed coverage.
- Review Policy and Compute Policy versions.
- Models used, measured usage, estimated or actual cost, and failure information;
  normal local CLI runs must expose the planned call count, estimated input
  tokens, and per-call output limit without inventing a dollar estimate.
- The data destination, provider, model, and known retention behavior used for
  analysis. A local command result must also expose a non-secret configuration
  fingerprint that binds its executable arguments, adapter, model, destination,
  and retention disclosure to the Compute Policy identity.
- During a local CLI run, text and JSON modes must expose non-authoritative
  preparation, stage, and current-dimension progress on stderr, including
  elapsed time for completed work.

The GitHub integration additionally publishes eligible findings inline, a
durable check result, and clear finding-bypass and GitHub-native override records
where observable.

The CLI additionally emits a human-readable terminal report, a stable
machine-readable result, and a documented process exit status. Its output must
include the resolved target ref, target-head commit, proposed-head or snapshot
commit, attempt identifier, Review Policy version, and merge-tree identifier
when available so a result cannot be mistaken for a later local state.
Construction failure represents the merge-tree identifier as unavailable. The
first-stage CLI does not create a bypass or update a remote check.

While the product is Pre-Alpha, the versioned CLI result schema
`worktree-review.cli.result/v1` may receive in-place identifier updates instead
of a new schema version. The shared pipeline stage that records Review Worktree
preparation is `prepare-review-worktree`; that value replaces the earlier
`prepare-workspace` identifier.

Presentation details, machine-readable schema, and platform UI mechanisms are
deferred to product interaction design and technical design.

## 20. Model and cost control requirements

For the first product stage, the product must support:

- The permitted provider and model.
- A safe hard output-token limit for each provider call.
- Behavior when the provider is unavailable or rate-limited.
- Advanced configuration of a maximum budget per review, token prices, and
  whether uncertain price or usage information permits a review to start.

The normal local CLI path must also accept a minimal trusted configuration that
specifies a remote provider, key, and optional model/URL, or a local command. It
uses a built-in Review Policy when none is supplied and derives a 4096-token
maximum output per call. A local command may use one of the product adapters
`worktree-json`, `prompt-json`, or `prompt-text-json`; the strict default sends
the Worktree Review JSON request, while the prompt adapters send the rendered
prompt to stdin and parse structured JSON output. Worktree Review must not claim
that an arbitrary existing executable understands the protocol without one of
these explicit adapter choices.

Selecting a local command is explicit consent to hand review content to that
command, but is not proof that it avoids network transmission or retention. The
configuration may describe the command's downstream data destination and known
retention; conservative defaults are disclosed when omitted. The derived Compute
Policy and result include a non-secret fingerprint of the complete command
configuration, while command arguments are not printed in disclosures. Before
calls begin, the CLI reports the planned call count, estimated input tokens, and
per-call output limit. After completion, it reports provider-measured usage when
available and does not invent a dollar cost when the provider does not return
one; users can consult provider account billing for actual spend.
More detailed compute controls remain available through trusted advanced
configuration.

When a provider does not expose reliable quota, usage, or price information,
Worktree Review must distinguish measured usage, user-declared limits, current price
estimates, and inferred availability. It must not present guesses as
authoritative, silently exceed an advanced configured budget, or imply that a
normal-path cost estimate is authoritative.

Multi-provider routing, time-based scheduling, quota optimization, and automatic
fallback are deferred until after the first product stage.

## 21. Review lifecycle

### 21.1 Shared review pipeline

After a surface resolves a target head and proposed head, both GitHub and CLI
execute the same ordered pipeline. Every stage records an explicit completed,
failed, or not-started outcome; a fatal failure cannot be hidden by later output.

1. Derive the review request key, create an attempt identifier, and record the
   execution provenance known before construction. A platform integration also
   atomically designates whether this attempt is authoritative.
2. Attempt to merge the proposed head into the resolved target head. Success
   finalizes the merge candidate identity and Review Identity. Failure produces
   `Error` bound to the review request key and attempt identifier, with no
   merge-tree identifier or completed Review Identity.
3. Prepare a complete, isolated, read-only Review Worktree.
4. Gather relevant context according to Review Policy.
5. Execute every review dimension required by Review Policy against that same
   Review Worktree and context, recording the completion outcome of each
   dimension.
6. Verify, deduplicate, and classify findings from all completed dimensions.
7. Check that every required dimension completed. If any did not, publish
   verified partial findings and coverage with `Error`; do not evaluate a passing
   gate decision.
8. Evaluate the deterministic gate rules.
9. Publish or return the findings, coverage, provenance, cost, review summary,
   and gate result through the invoking surface. A platform publication may
   change the standing decision only after an atomic check that this Attempt and
   Review Request Key are still authoritative, plus Review Identity whenever
   construction succeeded.

### 21.2 GitHub lifecycle

1. An eligible repository-branch pull request is opened, reopened, marked ready,
   updated, force-pushed, or retargeted; its target branch or applicable Review
   Policy changes; or an authorized user explicitly retries its unchanged review
   request, including after correcting Compute Policy or a transient failure.
2. Worktree Review resolves the current target branch and pull-request head.
3. Worktree Review creates a new attempt and atomically makes it authoritative. Any
   standing decision from the prior authoritative attempt is invalidated
   immediately, before review scheduling or candidate construction, whether the
   Review Identity changed or remained the same.
4. Worktree Review runs the shared review pipeline and publishes a durable GitHub check.
5. Publication atomically verifies the current Attempt ID and Review Request Key,
   plus Review Identity whenever construction succeeded. A superseded attempt
   remains audit-only.
6. A later identity change or explicit retry returns to step 2 for another
   complete review.

The first stage must expose an authorized retry action for the current GitHub
review request. Exact presentation through a check action, command, or details
page is interaction design, but the retry semantics are normative. Automatic
provider-request retries within an attempt follow Compute Policy and do not
replace this complete-review retry path.

Draft pull requests have no standing passing decision. External-fork pull
requests and hosted private repositories are reported as unsupported in the
first product stage rather than entering this lifecycle.

### 21.3 Local CLI lifecycle

1. The user runs `worktree-review init` once to interactively select and validate
   a remote provider/key or local command and write the trusted default config.
   The plain `worktree-review` command then starts a local review using that
   config; `worktree-review review` remains an equivalent explicit spelling.
   The target defaults to `HEAD`, may be selected with `--target`, or may be
   selected as `HEAD~N` with `--commits N` to review the last N commits. The
   proposed source defaults to the current worktree snapshot; `--proposed`
   selects an explicit committed ref.
2. The CLI resolves the target and captures the proposed source once. A dirty
   worktree is represented by an immutable snapshot commit containing tracked
   and non-ignored untracked files; a clean worktree uses the current `HEAD`.
   It then loads the product-owned built-in Review Policy unless a custom trusted
   Review Policy is supplied, loads the trusted provider configuration, and
   identifies the configured model provider, data destination, known retention
   behavior, and local configuration fingerprint. The normal provider
   configuration contains either a remote provider/key/model with an optional
   URL or a local command plus an explicit product adapter when the command does
   not consume the default Worktree Review JSON protocol. It uses the 4096-token
   per-call output limit, discloses local-command handoff semantics, and reports
   the call plan and progress before and during model calls.
3. The CLI creates an independent attempt identifier and runs the shared review
   pipeline against those immutable Git objects.
4. The CLI writes human-readable and machine-readable results and exits with the
   documented status for `Passed`, `Blocked`, `Error`, or invalid invocation.

A CLI result applies only to the review request key, attempt identifier, and any
successfully constructed identities printed in that result. It neither creates a
standing remote gate nor claims to cover commits or working-tree changes created
after the proposed source was captured.

## 22. Feedback and product validation

Quantitative success targets are not meaningful before Worktree Review has enough
representative usage and independently reviewed examples. The first stage
collects structured feedback including:

- Participant disposition for each finding: `confirmed`, `false positive`,
  `uncertain`, or `accepted risk`.
- Whether the gate decision matched the participant's own judgment.
- Whether review language, severity, evidence presentation, and repair guidance
  were useful.
- The participant role and whether no feedback was supplied.

Participant feedback is not treated as ground truth. When sufficient examples
exist, Worktree Review should maintain a separately adjudicated evaluation set for
real-problem discovery, false-positive, and false-block measurement. Cost and
latency remain operational diagnostics rather than quality substitutes.

The local CLI must not transmit feedback, source content beyond the declared
model request, or product-usage telemetry without explicit user opt-in.

## 23. Explicitly deferred technical decisions

This PRD does not decide:

- GitHub App versus GitHub Action implementation.
- Hosted versus self-hosted service topology.
- The internal adapter interface shared by GitHub, CLI, and future platforms.
- Future CLI packaging choices and machine-readable output evolution beyond the
  first-stage contract.
- Merge-candidate construction and Review Worktree lifecycle mechanisms.
- Queue, database, cache, or storage technology.
- Server storage mechanics for Review Policy and Compute Policy.
- Context retrieval implementation.
- Exact prompt wording and analysis algorithms beyond the required prompt-layer
  order.
- Optional numerical-confidence calibration.
- Credential brokering and read-only Review Worktree isolation mechanisms.
- GitHub API, webhook, checks, and comment mechanics.
- Later repository-platform adapter mechanics.
- Richer configuration fields and user prompt editing beyond the first-stage
  minimal provider configuration and inspectable built-in prompt hierarchy.
- Later-stage external-fork authorization and sandboxing.
- Hosted private-repository provider disclosure, retention, and opt-out controls.
- Incremental review and cross-candidate finding matching.
- Deep Review, interactive reassessment, and multi-provider routing.

These decisions belong in technical designs after this first-stage product
contract is accepted. A technical design may choose mechanisms, but it must
preserve the merge-candidate identity, fail-closed `Error`, complete-review, and
read-only-analysis requirements defined here.
