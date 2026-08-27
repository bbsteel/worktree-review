# MergeGate Product Requirements Document

- Status: First-stage product contract ready for technical design
- Date: 2026-08-20
- Visibility: Public product document
- Product form: Platform-independent review gate with GitHub and local CLI surfaces

This is a living description of the intended product direction, not a delivery
commitment. The first-stage requirements are normative for the initial product;
later-stage capabilities remain directional until promoted into that scope.

## 1. Product summary

MergeGate is a platform-independent, policy-driven AI review gate for proposed
code changes. It reviews the exact result that would be merged into a target,
publishes evidence-backed findings, and decides whether that merge candidate may
pass under user-owned review and compute policies.

MergeGate provides an open, user-controlled alternative for code-change review
and merge gating. Its long-term direction gives users control over review
standards, language, models, budgets, quotas, and routing.
GitHub is the first repository-platform integration, not the boundary of the
product. A local CLI exposes the same review semantics without requiring a pull
request. The first product stage deliberately implements a smaller, fail-closed
subset of this direction.

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

MergeGate addresses these problems by making review policy, compute policy,
merge-candidate context, evidence strength, review coverage, and the gate
decision first-class product concepts.

## 3. Product vision

Every eligible merge candidate should receive a context-complete review under
rules the policy owner controls. The result must say what was reviewed, what
was found, how strong the evidence is, what the review cost, and whether the
merge gate is open.

The product promise is:

> Your policies. Your models. Your merge gate.

## 4. Product form and platform scope

MergeGate has one platform-independent product contract exposed through multiple
surfaces:

| Surface | First-stage role | Result authority |
| --- | --- | --- |
| GitHub integration | Automatically reviews eligible pull requests, publishes inline findings and a durable check, and supports auditable finding bypass. | A standing gate decision bound to the current review identity. |
| Local CLI | Reviews an explicitly selected local merge candidate on demand and emits human-readable and machine-readable results. | A one-shot result and process exit status for the reviewed identity; it does not create or change a remote standing gate. |
| Other repository platforms | Later integrations map native change requests, checks, comments, and authorization onto the same MergeGate semantics. | Must preserve the same identity, evidence, coverage, and fail-closed rules. |

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
- On-demand CLI review of a committed local Git head against an explicitly
  selected target ref. The local worktree must be clean so the candidate is
  reproducible from Git objects.

Each distinct review identity receives a complete Standard Review. Both entry
points construct and review the same kind of merge candidate, apply the same
Review Policy and gate evaluation, and expose the exact identity reviewed. The
first stage does not reuse review conclusions incrementally across candidates.

MergeGate must:

1. Automatically review an eligible GitHub pull request when it is opened,
   reopened, marked ready for review, or updated.
2. Let a user start the same review locally through the CLI by selecting a target
   ref and committed proposed head.
3. Review the merge candidate produced by merging the proposed head into the
   resolved target head, rather than reviewing the proposed head alone.
4. Bind every result to its source repository, target ref, resolved target head,
   proposed head, resulting merge tree, and Review Policy version; a platform
   change-request identifier is additional provenance when one exists.
5. Immediately invalidate a standing platform gate when any part of its review
   identity changes; invalidation happens before a replacement review starts.
6. Prepare a complete, isolated, read-only workspace for the exact merge
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
13. Give the CLI stable, documented process exit behavior, with success for
    `Passed` and distinct nonzero outcomes for `Blocked`, `Error`, and invalid
    invocation.
14. Offer repair guidance without modifying the proposed change.
15. Let users encode and version their review experience as policy stored outside
    the repository under review.
16. Let users select the permitted provider and model and set a per-review budget.
17. Fail explicitly when a complete review cannot finish, including when the
    merge candidate cannot be constructed or the budget is exhausted.
18. Make the merge-candidate identity, policy versions, model usage, cost,
    coverage, and failure behavior visible on every surface.

## 7. First-stage boundaries

### 7.1 Deferred product capabilities

The following capabilities remain part of the product direction but are not
requirements for the first product stage:

- Reviews of pull requests from external forks.
- Hosted reviews of private repositories.
- Local review of uncommitted or dirty-worktree snapshots.
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

MergeGate is not intended to be:

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

MergeGate may provide a suggested fix or illustrative patch, but it does not
apply, commit, or push that fix in the first stage.

## 8. Product principles

### 8.1 Exact merge candidate or no review

The review subject is the result of merging a committed proposed head into a
resolved target head. The target head is not the historical merge-base. GitHub
resolves these commits from the current pull request; the CLI resolves them from
the explicitly selected target ref and proposed head. If either resolved commit
changes, a new merge candidate exists.

If MergeGate cannot construct the merge candidate, including because of a merge
conflict, the review ends with `Error`. A head-only worktree has no gate value and
must not produce a passing decision.

### 8.2 Decisions are identity-bound

MergeGate distinguishes related identities:

- Merge candidate identity: source repository, target ref, resolved target-head
  commit, proposed-head commit, and the resulting merge-tree identifier when
  construction succeeds. A platform change-request identifier is provenance,
  not a substitute for these Git identities.
- Review identity: merge candidate identity plus the applied Review Policy
  version.
- Finding identity: a finding within one review identity.
- Bypass identity: the review identity, finding identity, and the stated risk
  that the authorized user chose to bypass.

Every execution records the invoking surface, Compute Policy version, selected
model provenance, and an attempt identifier as audit fields. These fields do not
create another product identity.

A standing platform gate decision is valid only for its review identity. A
target-ref change, target-head change, proposed-head change, retarget, or
applicable Review Policy change invalidates the old decision immediately. An
eligible GitHub pull request then starts a new complete review. Superseded queued
or in-flight reviews must not publish a standing decision. A CLI result remains a
one-shot result for the exact identity printed in its output and is never a
standing decision for later local state.

A Compute Policy change can change what a later review discovers, but it does not
change the meaning of Review Policy. It does not silently invalidate a completed
decision; explicitly reviewing again withdraws that decision until the new
review completes.

### 8.3 Context-complete by default

Standard Review must use all relevant context required by Review Policy. Lower
latency or cost may be achieved through retrieval, caching, or model choice, but
not by reducing the required review scope.

### 8.4 No silent degradation

MergeGate must never represent a partial or failed review as a successful
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

Policy owners control the permitted provider, model, and per-review budget in the
first stage. Later compute policies may add routing, quotas, scheduling, and
fallback without changing Review Policy semantics.

### 8.8 Bypass is not resolution

A bypass records that an authorized user chose to proceed despite the stated
risk. It must not be displayed as if MergeGate withdrew the finding or
determined that the code was safe.

### 8.9 Policy never comes from the reviewed repository

Review Policy and Compute Policy are stored under MergeGate's control and are
never loaded from the Git refs or merge tree under review. GitHub uses policy
held by its MergeGate installation; the CLI uses an explicitly selected trusted
policy outside the reviewed repository. A proposed change can therefore never
modify the rules that gate it. Repository instruction files such as `AGENTS.md`
and `CLAUDE.md` are review context, not policy.

### 8.10 Repository content is data, not instructions

Everything under review, including code, comments, linked issues, change-request
discussion, and participant-supplied evidence, is untrusted input. It may inform
findings, but it must never override policy or control reviewer tools.

### 8.11 First-stage analysis is read-only

The first stage retrieves files and performs model analysis but does not execute
proposed-change code, tests, build scripts, hooks, or binaries. The review
workspace cannot access platform credentials, installation tokens, or
model-provider credentials. Tool, file-system, and network permissions come only
from trusted product policy. Findings and logs must redact complete credentials
and other detected secrets.

Before a CLI review sends repository content to a remote model provider, it must
identify the provider, model, data destination, and known retention behavior and
require explicit trusted configuration that permits that transmission. Local
execution of the CLI must never imply that model inference or data retention is
local.

### 8.12 Product semantics are portable

The GitHub integration and local CLI share merge-candidate construction, Review
Policy, Compute Policy, evidence bands, coverage rules, finding structure, and
gate evaluation. A platform adapter may map these concepts to native checks,
comments, permissions, and events, but it must not weaken or reinterpret them.

## 9. Core concepts

### 9.1 Merge Candidate Workspace

Every execution of a review uses an isolated, complete, read-only workspace
containing the exact merge result for its merge candidate identity. The
workspace records both parent commits and the resulting tree or merge commit
used for review.

The product requires workspace isolation, revision traceability, and protection
from superseded reviews. The construction and storage mechanisms are deferred to
technical design.

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

Review Policy must be reusable and versionable. It is stored under MergeGate's
control, never in the reviewed repository. Its storage format and evaluation
mechanism are deferred.

### 9.3 Compute Policy

For the first product stage, Compute Policy governs:

- The permitted provider and model for a review.
- The maximum budget per review.
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

A finding is scoped to one review identity in the first product stage. MergeGate
does not promise to preserve finding identity across merge candidates. When the
same review identity is reviewed again, MergeGate may recognize a materially
unchanged finding so that an applicable bypass remains auditable, but it must not
transfer a bypass to a materially different risk.

### 9.5 Gate decision

The gate decision is a deterministic policy evaluation over required-dimension
completion, completed review coverage, and unresolved findings. It is not a raw
model response. Model analysis may change which findings exist; the mapping from
dimension completion, coverage, finding severity, evidence band, and bypass
state to the gate decision must not vary by model.

## 10. Review scope and context

Standard Review may use all relevant context available through the invoking
surface and within first-stage scope, including:

- Change-request title and description when a platform integration supplies them.
- Linked public issues and acceptance criteria when available.
- The complete merge-candidate diff and changed files.
- Callers, callees, public interfaces, data structures, and dependencies.
- Relevant tests and test intent, without executing the tests.
- Review Policy stored under MergeGate's control.
- Repository instruction files such as `AGENTS.md` and `CLAUDE.md`, treated as
  untrusted context.
- Relevant architecture, product, and business documentation in the reviewed
  repository.
- Existing change-request discussion when available.
- The resolved target implementation represented in the merge candidate.
- Relevant commit history.
- Available results from CI, tests, linters, and security checks run outside the
  MergeGate review workspace.

Review Policy classifies context as follows:

| Context class | Product behavior when unavailable or unreadable |
| --- | --- |
| Mandatory | The review ends with `Error`. |
| Optional | The review may complete, but the missing context is disclosed in coverage. |
| Explicitly excluded | The content is outside policy scope and is disclosed as excluded. |
| Unreviewable changed content | Review Policy must explicitly exclude it; otherwise the review ends with `Error`. |

Unreviewable content may include binaries, unavailable Git LFS objects, or files
that exceed supported limits. MergeGate must not silently skip such content and
claim complete coverage.

Context completeness means complete coverage of the scope required by the
applied Review Policy, not possession of all possible knowledge. Missing evidence
for one suspected issue must not be promoted into a blocking finding; missing
mandatory context for the review instead produces `Error`.

## 11. Review mode

### 11.1 Standard Review

Standard Review is the only first-stage review mode. It:

- Starts automatically for every new review identity of an eligible GitHub pull
  request and on demand for each CLI invocation.
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

When a new GitHub review identity appears while a review is queued or in flight,
the old standing decision becomes invalid immediately and the superseded review
is abandoned. A new complete review is then queued. Implementations may coalesce
superseded work for cost control, but they must never leave the previous gate
decision standing.

The CLI resolves its target and proposed head once at invocation time and reviews
those immutable Git objects. It must refuse a dirty worktree in the first stage,
report the resolved identities, and never imply that its result covers commits or
working-tree changes created after that resolution.

Draft pull requests are not eligible for review. Marking a pull request ready
starts review; converting it back to draft invalidates any standing MergeGate
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

Self-reported model certainty is not evidence. Review Policy defines the minimum
evidence band required for blocking, and that definition remains stable across
models.

MergeGate may display a numerical or human-readable confidence diagnostic when
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
| `Error` | MergeGate could not complete every required review dimension, required coverage, or a valid gate decision. |

`Error` is fail-closed. Finding bypass is unavailable for an incomplete review,
and no product action converts `Error` to `Passed with bypass`. The only product
path out of `Error` is to correct or change the blocking condition and rerun the
review successfully. A platform administrator may use a platform-native
administrative bypass when one exists, but MergeGate keeps its state as `Error`
and records no passing decision. The CLI returns its documented nonzero `Error`
outcome.

When a platform review identity changes, the prior state ceases to be the
standing gate before the replacement review begins. The new identity moves
through `Awaiting review` and `In progress`; it never inherits `Passed`, `Passed
with bypass`, or a finding bypass from the previous identity. CLI invocations do
not inherit a gate or bypass from prior invocations.

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

MergeGate may provide:

- A repair direction.
- An illustrative code snippet or patch.
- Recommended tests.
- Relevant examples from the repository.

MergeGate does not apply, commit, or push the repair in the first stage. A
suggested repair is not verified until the author creates a new merge candidate
and MergeGate completes its review.

## 18. Budget exhaustion and incomplete review

If the configured budget cannot cover a complete review:

- The gate state is `Error`.
- MergeGate reports that the budget was exhausted.
- Completed, excluded, optional-missing, and unreviewed scope is visible.
- Findings already discovered may remain visible but cannot be bypassed.
- No `Passed` or `Passed with bypass` decision is produced.
- The user may change Compute Policy and rerun the same review identity.

The same fail-closed behavior applies to provider failure, an incomplete required
review dimension, unavailable mandatory context, unreviewable in-scope content,
missing workspace, merge conflict, or any other condition that prevents a
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
- Merge-candidate and review identity.
- Completion or failure status for candidate construction, workspace preparation,
  context gathering, every review dimension required by Review Policy, and gate
  evaluation.
- Mandatory, optional-missing, excluded, unreviewable, and reviewed coverage.
- Review Policy and Compute Policy versions.
- Models used, measured usage, estimated or actual cost, and failure information.
- The data destination, provider, model, and known retention behavior used for
  analysis.

The GitHub integration additionally publishes eligible findings inline, a
durable check result, and clear finding-bypass and GitHub-native override records
where observable.

The CLI additionally emits a human-readable terminal report, a stable
machine-readable result, and a documented process exit status. Its output must
include the resolved target ref, target-head commit, proposed-head commit,
merge-tree identifier, and Review Policy version so a result cannot be mistaken
for a later local state. The first-stage CLI does not create a bypass or update a
remote check.

Presentation details, machine-readable schema, and platform UI mechanisms are
deferred to product interaction design and technical design.

## 20. Model and cost control requirements

For the first product stage, users must be able to configure:

- The permitted provider and model.
- A maximum budget per review.
- Behavior when the provider is unavailable or rate-limited.
- Whether uncertain price or usage information permits a review to start.

When a provider does not expose reliable quota, usage, or price information,
MergeGate must distinguish measured usage, user-declared limits, current price
estimates, and inferred availability. It must not present guesses as
authoritative or silently exceed the configured budget.

Multi-provider routing, time-based scheduling, quota optimization, and automatic
fallback are deferred until after the first product stage.

## 21. Review lifecycle

### 21.1 Shared review pipeline

After a surface resolves a target head and proposed head, both GitHub and CLI
execute the same ordered pipeline. Every stage records an explicit completed,
failed, or not-started outcome; a fatal failure cannot be hidden by later output.

1. Derive the merge-candidate and review identities.
2. Attempt to merge the proposed head into the resolved target head. Failure
   produces `Error` for that review identity.
3. Prepare a complete, isolated, read-only Merge Candidate Workspace.
4. Gather relevant context according to Review Policy.
5. Execute every review dimension required by Review Policy against that same
   workspace and context, recording the completion outcome of each dimension.
6. Verify, deduplicate, and classify findings from all completed dimensions.
7. Check that every required dimension completed. If any did not, publish
   verified partial findings and coverage with `Error`; do not evaluate a passing
   gate decision.
8. Evaluate the deterministic gate rules.
9. Publish or return the findings, coverage, provenance, cost, review summary,
   and gate result through the invoking surface.

### 21.2 GitHub lifecycle

1. An eligible repository-branch pull request is opened, reopened, marked ready,
   updated, force-pushed, or retargeted; or its target branch or applicable Review
   Policy changes.
2. MergeGate resolves the current target branch and pull-request head.
3. Any standing decision for a different review identity is invalidated
   immediately, before review scheduling or candidate construction.
4. MergeGate runs the shared review pipeline and publishes a durable GitHub check.
5. A later identity change returns to step 2 for another complete review.

Draft pull requests have no standing passing decision. External-fork pull
requests and hosted private repositories are reported as unsupported in the
first product stage rather than entering this lifecycle.

### 21.3 Local CLI lifecycle

1. The user invokes MergeGate inside a local Git repository and explicitly
   selects a target ref; the proposed head defaults to the committed `HEAD` but
   may be another committed ref.
2. The CLI verifies that the worktree is clean, resolves both refs to immutable
   commits, loads trusted policy from outside the reviewed repository, and
   identifies the configured model provider, data destination, and known
   retention behavior.
3. The CLI runs the shared review pipeline against those resolved Git objects.
4. The CLI writes human-readable and machine-readable results and exits with the
   documented status for `Passed`, `Blocked`, `Error`, or invalid invocation.

A CLI result applies only to the identities printed in that result. It neither
creates a standing remote gate nor claims to cover later commits or uncommitted
working-tree changes.

## 22. Feedback and product validation

Quantitative success targets are not meaningful before MergeGate has enough
representative usage and independently reviewed examples. The first stage
collects structured feedback including:

- Participant disposition for each finding: `confirmed`, `false positive`,
  `uncertain`, or `accepted risk`.
- Whether the gate decision matched the participant's own judgment.
- Whether review language, severity, evidence presentation, and repair guidance
  were useful.
- The participant role and whether no feedback was supplied.

Participant feedback is not treated as ground truth. When sufficient examples
exist, MergeGate should maintain a separately adjudicated evaluation set for
real-problem discovery, false-positive, and false-block measurement. Cost and
latency remain operational diagnostics rather than quality substitutes.

The local CLI must not transmit feedback, source content beyond the declared
model request, or product-usage telemetry without explicit user opt-in.

## 23. Explicitly deferred technical decisions

This PRD does not decide:

- GitHub App versus GitHub Action implementation.
- Hosted versus self-hosted service topology.
- The internal adapter interface shared by GitHub, CLI, and future platforms.
- CLI packaging, command syntax, configuration discovery, and machine-readable
  output schema.
- Merge-candidate construction and workspace lifecycle mechanisms.
- Queue, database, cache, or storage technology.
- Review Policy and Compute Policy storage schemas.
- Context retrieval implementation.
- Model prompting and analysis algorithms.
- Optional numerical-confidence calibration.
- Credential brokering and read-only workspace isolation mechanisms.
- GitHub API, webhook, checks, and comment mechanics.
- Later repository-platform adapter mechanics.
- Configuration file schema.
- Later-stage external-fork authorization and sandboxing.
- Hosted private-repository provider disclosure, retention, and opt-out controls.
- Incremental review and cross-candidate finding matching.
- Deep Review, interactive reassessment, and multi-provider routing.

These decisions belong in technical designs after this first-stage product
contract is accepted. A technical design may choose mechanisms, but it must
preserve the merge-candidate identity, fail-closed `Error`, complete-review, and
read-only-analysis requirements defined here.
