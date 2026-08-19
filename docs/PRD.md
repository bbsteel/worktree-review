# MergeGate Product Requirements Document

- Status: Product direction approved; scope may evolve during implementation
- Date: 2026-08-19
- Visibility: Public product document

This is a living description of the intended product direction, not a delivery
commitment. Implementation sequencing and technical design may change as the
product is validated.

## 1. Product summary

MergeGate is a GitHub-native, policy-driven AI review gate for pull requests. It automatically reviews every pull request change in a complete repository worktree, publishes evidence-backed inline findings, and decides whether the change may merge according to user-owned review and compute policies.

MergeGate provides an open, repository-owner-controlled alternative for core pull-request review and merge gating. Users control the review standards, language, models, budgets, quotas, and routing strategies.

## 2. Problem statement

Independent developers and small open-source repositories can encounter limitations in AI-assisted review workflows:

- Automatic-review eligibility may vary by repository or service plan.
- Reviews may stop or require manual triggering after configured usage thresholds are reached.
- Review language and severity presentation may not match the user's needs.
- Users cannot fully control which models are used, how quota is consumed, or how providers are switched.
- Generic review prompts do not preserve an experienced reviewer's standards in a reusable, testable form.
- Diff-only reviews can miss behavior that is visible only through callers, callees, tests, configuration, documentation, and business requirements.
- A review bot may publish comments without providing a dependable merge decision.

MergeGate addresses these problems by making the review policy, compute policy, complete worktree context, evidence, confidence, and gate decision first-class product concepts.

## 3. Product vision

Every pull request should receive a context-complete review under rules the repository owner controls. The result must say what was reviewed, what was found, how confident MergeGate is, what it cost, and whether the merge gate is open.

The product promise is:

> Your policies. Your models. Your merge gate.

## 4. Target users

### 4.1 Primary user

An experienced individual developer or small-project maintainer who:

- Uses coding agents and produces pull requests frequently.
- Reviews their own branches and external contributions.
- Has substantial code-review experience they want to reuse.
- Wants high-confidence findings rather than high comment volume.
- Wants to configure review language and severity behavior.
- Wants to select and route among multiple LLM providers.
- Wants explicit control over cost, quota, timing, and fallback behavior.
- Does not accept repository popularity as an eligibility criterion.

### 4.2 Later users

- Small engineering teams sharing review policies across repositories.
- Open-source maintainers reviewing external fork pull requests.
- Organizations that need auditable, repository-owned merge policies.

## 5. Goals

MergeGate must:

1. Automatically review new and updated pull requests.
2. Provide the same review experience for repository branches and external forks; reviews of external-fork pull requests are triggered manually by the repository owner or a committer, never automatically.
3. Review from a complete, isolated worktree for the exact pull-request revision.
4. Gather relevant code and business context on demand from that worktree.
5. Publish inline findings with severity, confidence, evidence, and impact.
6. Support `critical`, `major`, `minor`, and `suggestion` findings.
7. Produce an explicit `Passed`, `Passed with bypass`, `Blocked`, or `Error` gate result.
8. Re-evaluate findings after code changes or evidence supplied in discussion.
9. Support a manually triggered Deep Review without weakening the default review's context.
10. Allow authorized users to bypass a blocking finding for the current revision with an auditable reason.
11. Offer repair guidance without modifying the pull request.
12. Let users encode and reuse their own review experience as policy.
13. Let users control model selection, routing, quotas, budgets, and scheduling.
14. Fail explicitly when the review cannot complete, including when budget is exhausted.
15. Make actual model usage, cost, coverage, and fallback behavior visible.

## 6. Non-goals for the first product stage

The first stage is not intended to be:

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

MergeGate may provide a suggested fix or illustrative patch, but it does not apply, commit, or push that fix in the first stage.

## 7. Product principles

### 7.1 Complete worktree or no review

A complete worktree for the exact pull-request revision is a mandatory prerequisite. A review performed without it has no product value and must not produce a passing gate result.

Complete worktree access does not mean reading every file. It means MergeGate can retrieve any relevant caller, callee, type, test, configuration, documentation, or neighboring implementation when evidence requires it.

If a complete worktree cannot be prepared or queried, the review ends with `Error`.

### 7.2 Context-complete by default

The automatic Standard Review must use complete relevant business and code context. Lower latency or cost may be achieved through model choice, caching, routing, or other implementation strategies, but never by intentionally removing required context.

### 7.3 No silent degradation

MergeGate must never represent a partial or failed review as a successful review. Skipped files, missing context, exhausted budget, provider failure, and incomplete coverage must be visible.

### 7.4 Evidence before enforcement

A model statement is not itself a gate decision. Blocking findings require sufficient confidence and evidence under the configured policy.

### 7.5 User-owned policy

Repository owners control what is reviewed, what severity means, which confidence is sufficient, which findings block, and who may bypass.

### 7.6 User-owned compute

Repository owners control providers, models, budgets, quotas, timing strategies, and fallback behavior. There are no hidden product-level throttles or popularity gates.

### 7.7 Bypass is not resolution

A bypass records that an authorized user accepted a known risk. It must not be displayed as if MergeGate withdrew the finding or determined that the code was safe.

### 7.8 Policy never comes from the reviewed repository

Review Policy and Compute Policy are stored under MergeGate's control and are never read from files in the repository under review — neither from the pull-request head nor from the target branch. A pull request can therefore never modify the rules that gate it. Repository instruction files such as `AGENTS.md` and `CLAUDE.md` are review context, not policy.

### 7.9 Repository content is data, not instructions

Everything under review — code, comments, linked issues, pull-request discussion, and evidence supplied by participants — is untrusted input. It may inform findings, but it must never act as instructions to the reviewer or override policy.

## 8. Core concepts

### 8.1 Pull Request Workspace

Each pull request revision has an isolated, complete repository workspace corresponding to an exact head commit. It provides the source of truth for code-context retrieval and finding verification.

The product requires workspace isolation and revision traceability. The implementation mechanism is deferred to technical design.

### 8.2 Review Policy

A Review Policy captures the user's review experience and governs:

- Review categories and priorities.
- Severity definitions.
- Confidence thresholds.
- Evidence requirements.
- Blocking behavior.
- Path-, language-, and component-specific rules.
- Positive examples, negative examples, and accepted exceptions.
- Comment presentation and output language.
- Bypass permissions and requirements.

Review Policy must be reusable and versionable. Per principle 7.8, it is stored under MergeGate's control, never in the reviewed repository. Its storage format and evaluation mechanism are deferred.

### 8.3 Compute Policy

A Compute Policy governs how review compute is allocated:

- Available providers and models.
- Model roles and review categories.
- Cost limits per review.
- Provider quota and plan constraints.
- Time-based routing rules.
- Provider availability and fallback behavior.
- Escalation to stronger or independent models.
- Deep Review budgets.

Compute Policy changes must not silently change the meaning of Review Policy. Per principle 7.8, Compute Policy is also stored under MergeGate's control, never in the reviewed repository.

### 8.4 Finding

A finding is a structured claim about a pull-request change. It includes at least:

- Location and affected code.
- Category.
- Severity.
- Confidence.
- Problem statement.
- Expected impact.
- Supporting evidence.
- Relevant policy rule, when applicable.
- Suggested repair direction, when useful.
- Review revision, the policy versions applied, and provenance.

A finding has identity across revisions. MergeGate must recognize the same finding on a new revision despite ordinary code displacement. If a finding can no longer be located or matched on the new revision, the affected scope is re-reviewed rather than the finding being silently dropped.

### 8.5 Gate decision

The gate decision is a policy evaluation over completed review coverage and unresolved findings. It is not a raw model response.

## 9. Review scope and context

Standard Review and Deep Review may use all relevant context available within the product scope, including:

- Pull-request title and description.
- Linked GitHub issues and acceptance criteria.
- The full diff and complete changed files.
- Callers, callees, public interfaces, data structures, and dependencies.
- Relevant tests and test intent.
- The repository's Review Policy (stored under MergeGate's control, per principle 7.8).
- Repository instruction files such as `AGENTS.md` and `CLAUDE.md`, treated as untrusted context per principle 7.9.
- Relevant architecture, product, and business documentation.
- Existing pull-request discussion and evidence supplied by participants.
- The target branch implementation.
- Relevant commit history and prior changes.
- Available CI, test, linter, and security-check results.

Context completeness means having sufficient relevant context to support a finding. When required context is missing, MergeGate must identify what is missing and avoid promoting unsupported speculation into a blocking finding.

## 10. Review modes

### 10.1 Standard Review

Standard Review is automatic and is the default product experience. It:

- Runs for new and updated pull requests.
- Covers all changed files unless an explicit Review Policy exclusion applies.
- Uses complete relevant business and code context.
- Reviews correctness, security, performance, architecture, maintainability, and style.
- Optimizes for reasonable latency and cost without reducing required context.
- Produces a complete gate decision.

Standard Review is incremental across revisions:

- On the first revision of a pull request, it performs a complete review and records the review context used for that review.
- On a subsequent revision, it reviews only the new changes when they fall within the recorded review context, re-evaluating existing findings alongside them.
- When the new changes extend beyond the recorded review context, it performs a new complete review of the revision and records fresh context.
- When the pull request is updated while a review is in flight, the in-flight review is abandoned and a new review starts for the new head revision.

Incrementality never reduces the context available to a review; it reuses context that was already gathered and is still sufficient. The mechanism for deciding whether new changes exceed the recorded context is deferred to technical design.

Standard Review must not be called Quick Review because lower latency does not imply reduced context or reduced review validity.

### 10.2 Deep Review

Deep Review is manually triggered. It:

- Uses the same complete worktree and context guarantees as Standard Review.
- Allocates additional compute or independent review passes.
- May invoke more specialized review strategies.
- May discover additional blocking findings.
- Temporarily returns the current revision to an in-progress gate state. This is intentional: requesting a Deep Review withdraws the standing gate decision — including a `Passed` result — until the stronger review completes.
- Supersedes the Standard Review gate decision for the same revision when complete.

Deep Review increases analysis strength, not context completeness.

## 11. Severity model

| Severity | Product meaning | Default gate behavior |
| --- | --- | --- |
| `critical` | A high-impact failure such as exploitable security compromise, authorization bypass, credential exposure, certain data loss, or a clear severe production-failure path. | Block |
| `major` | A real functional defect, material regression, important compatibility break, concurrency or transaction error, or significant performance failure. | Block |
| `minor` | A limited edge case or concrete maintainability, correctness, or performance issue with restricted impact. | Non-blocking |
| `suggestion` | An optional improvement, alternative design, naming improvement, style preference, or nonessential refactor. | Non-blocking |

Review Policy may change blocking behavior, but the default is that unresolved `critical` and `major` findings block.

## 12. Confidence and real-problem judgment

Confidence is the primary signal for deciding whether a reported concern is likely to be a real problem. Severity and confidence are independent:

- Severity describes impact if the finding is true.
- Confidence describes how strongly available evidence supports that it is true.

Confidence should be exposed as a normalized score with a human-readable band. Exact calibration and computation are deferred to technical design.

A finding's confidence must reflect evidence such as:

- A reachable execution or data path.
- A violated contract or acceptance criterion.
- A caller/callee mismatch.
- A reproducible or logically necessary failure condition.
- A conflicting test, type, configuration, or established repository pattern.
- Independent confirmation when policy requires it.

Self-reported model certainty without supporting evidence is insufficient for blocking.

Review Policy defines the minimum confidence required for a blocking decision. A high-severity, low-confidence hypothesis may trigger further investigation or Deep Review but must not automatically become a valid blocking finding.

## 13. Gate states

| Gate state | Meaning |
| --- | --- |
| `In progress` | Review for the current revision has not completed. |
| `Passed` | Review completed and no unresolved blocking findings remain. |
| `Passed with bypass` | Valid blocking findings remain — or the review ended in `Error` with partial results — but authorized users explicitly accepted the risk for this revision. |
| `Blocked` | One or more sufficiently confident, unresolved, non-bypassed blocking findings remain. |
| `Error` | MergeGate could not complete a valid review or gate decision. |

`Error` is fail-closed: it does not open the gate.

An unresolved blocking finding is a finding at a severity that blocks under the current Review Policy which has not been resolved, withdrawn, downgraded below the blocking severity, or bypassed. A finding downgraded below the blocking severity no longer blocks the gate, so downgrading a `major` finding to `minor` can turn a `Blocked` gate into `Passed`.

## 14. Finding interaction and reassessment

Participants may reply to a finding with additional evidence. MergeGate evaluates the evidence against the pull-request workspace, Review Policy, and business context.

Reassessment outcomes are:

- `Resolved`: The code change fixes the issue.
- `Withdrawn`: New evidence shows the original finding was not valid.
- `Downgraded`: The issue remains but has lower impact than originally assessed.
- `Retained`: The evidence is insufficient to change the finding.

MergeGate must explain the evidence behind a retained blocking finding. Conversation tone or insistence alone must not change the decision.

## 15. Bypass

An authorized GitHub user may bypass a valid blocking finding. Bypass behavior must:

- Require an explicit reason.
- Record the actor, time, pull request, revision, and affected finding.
- Apply only to the intended finding on the revision on which it is granted; a new revision expires all bypasses.
- Be final for that finding on that revision: once granted, no reassessment, policy threshold, or repeated review of the same revision can make the bypassed finding block the gate again.
- Preserve future enforcement for unrelated or newly introduced findings.
- Remain visibly distinct from resolution or withdrawal; bypassed findings stay visible.
- Coexist with GitHub's native administrative bypass capabilities.

A bypass may also be granted while the gate is `Error` — for example, when budget was exhausted with partial findings visible. Bypassing the remaining blocking findings then records explicit acceptance of the incomplete review as well, and the gate becomes `Passed with bypass`. The incomplete coverage remains visible per §17: a bypass never converts a partial review into a complete one.

The default authorization model should align with GitHub review permissions and support restricting bypass to requested reviewers other than the pull-request author. Exact authorization mapping is deferred.

## 16. Repair suggestions

MergeGate may provide:

- A repair direction.
- An illustrative code snippet or patch.
- Recommended tests.
- Relevant examples from the repository.

MergeGate does not apply, commit, or push the repair in the first stage. A suggested repair is not considered verified until the author updates the pull request and MergeGate reviews the new revision.

## 17. Budget exhaustion and incomplete review

If the configured budget cannot cover a complete review:

- The gate state is `Error`.
- MergeGate reports that budget was exhausted.
- Completed and unreviewed scope is visible.
- Findings already discovered may remain visible.
- MergeGate does not itself produce a `Passed` or `Passed with bypass` decision. The paths out of `Error` are rerunning the review under a policy that can complete, or bypassing the remaining blocking findings (§15), which records explicit acceptance of the incomplete review.
- The user may change budget or model policy and rerun the review.

The same behavior applies to unrecoverable provider failure, missing workspace, missing mandatory context, or any other condition that prevents complete review.

## 18. Output and localization

The user can configure the review output language. Localization applies to explanations and interaction while preserving source identifiers, API names, code, and exact error messages where translation would reduce precision.

The pull-request experience includes:

- Inline findings.
- Severity and confidence.
- Evidence and impact.
- Suggested repairs when appropriate.
- A review summary.
- Gate state.
- Review coverage.
- Models and policies used.
- Cost and fallback information.
- Clear error and bypass records.

Presentation details and GitHub UI mechanisms are deferred to product interaction design and technical design.

## 19. Model and cost control requirements

Users must be able to express policies that account for:

- Pull-request risk.
- Review category.
- Provider price.
- Provider quota or plan allowance.
- Time of day or other scheduling windows.
- Model availability and rate limiting.
- Per-review maximum budget.
- Escalation and independent verification.
- Manual Deep Review.

When a provider does not expose reliable quota information, MergeGate must distinguish measured usage, user-declared limits, and inferred availability. It must not present guessed quota as authoritative.

## 20. Pull-request lifecycle

The expected product flow is:

1. A pull request is opened or updated. For repository branches, review starts automatically; for external forks, the repository owner or a committer starts it manually.
2. MergeGate starts Standard Review for the exact revision, abandoning any in-flight review of a superseded revision.
3. MergeGate prepares a complete Pull Request Workspace.
4. Relevant business and code context is gathered as needed, reusing the recorded review context when it still covers the changes (§10.1).
5. Findings are generated, verified, deduplicated, and classified; existing findings are matched to the new revision (§8.4).
6. Inline findings and a review summary are published.
7. MergeGate produces a gate decision.
8. The author changes code or supplies evidence.
9. MergeGate reviews the new revision — incrementally when the changes fall within the recorded review context, completely when they extend beyond it — and re-evaluates existing findings.
10. The gate passes, remains blocked, is bypassed by an authorized user, or reports an error.

The same user-facing lifecycle applies to repository branches and external forks, with one exception: external-fork reviews never start automatically. This prevents untrusted contributors from consuming the owner's review compute at will.

## 21. Feedback

Quantitative success targets are not meaningful at this stage. MergeGate instead collects structured feedback from the people and agents whose pull requests are reviewed:

- Whether each finding was a real problem — already captured as a by-product of normal use through reassessment outcomes (`Resolved`, `Withdrawn`, `Downgraded`, `Retained`) and bypass records.
- Whether the gate decision matched the review participant's own judgment.
- Whether review language, severity, and confidence presentation were useful.

This feedback is reviewed qualitatively to guide product direction. Quantitative discovery and false-block metrics may be defined later, once there is enough usage to calibrate them. Cost and latency remain operational diagnostics.

## 22. Explicitly deferred technical decisions

This PRD does not decide:

- GitHub App versus GitHub Action implementation.
- Hosted versus self-hosted service topology.
- Worktree creation and lifecycle mechanisms.
- Queue, database, cache, or storage technology.
- Model-routing algorithms.
- Confidence calibration algorithms.
- Context retrieval implementation, including the recorded review context used for incremental review.
- Finding identity matching across revisions.
- Policy storage and versioning mechanisms.
- Sandbox and untrusted-fork isolation implementation.
- GitHub API, webhook, checks, and comment mechanics.

These decisions belong in a separate technical design after this PRD is reviewed and accepted.
