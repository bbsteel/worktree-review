# Worktree Review usage

This guide describes the currently usable Worktree Review surface: the local
`worktree-review` CLI. It covers installation, minimal provider configuration,
the built-in review policy and prompt hierarchy, source selection, output, and
exit codes.

The GitHub server has some state, webhook, retry, and Checks adapter pieces, but
its review worker is not connected to the shared pipeline yet. It is not an
end-to-end user-facing review service in this stage.

## Requirements

- Python 3.12 or newer.
- Git 2.38 or newer. Worktree Review uses `git merge-tree --write-tree`.
- A local Git repository with a resolvable target and proposed commit.
- Either a remote provider key and model (with an optional custom URL), or a
  local review command with one of the built-in local adapters.

The CLI does not execute code from the proposed change. It constructs an exact
merge candidate, materializes a temporary read-only Review Worktree, gathers
policy-selected context, and hands the resulting review request to the
configured provider or local command.

## Install

When working from this repository:

```bash
uv sync
uv run worktree-review --version
```

For an installed package, use the package manager appropriate for your
environment:

```bash
uv tool install worktree-review
# or
pipx install worktree-review
```

The installed command is `worktree-review`. The `uv run` prefix is needed only
when using the checkout's virtual environment directly.

## Quick start

Create the trusted default configuration interactively, then run the review from
the repository:

```bash
worktree-review init
worktree-review
```

`init` records a remote provider/key or local command in
`~/.config/worktree-review/config.yaml`. It checks that a local executable can
be found but does not execute it, and it does not make a remote credential
request. `worktree-review review` remains the explicit equivalent of the plain
command.

## Configuration files

For the normal local CLI flow, the user-facing configuration is one small YAML
file. It selects either a remote provider with a key and model (plus an optional
custom URL), or a local review command. Review Policy is optional: if `--policy`
is omitted, Worktree Review uses its built-in default policy. `worktree-review
init` is the recommended way to create this file; manual YAML is useful when
configuration is managed by a secret store or deployment system.

Copy [config.example.yaml](config.example.yaml) to the trusted default location
and replace the key reference:

```bash
mkdir -p ~/.config/worktree-review
cp config.example.yaml ~/.config/worktree-review/config.yaml
export ANTHROPIC_API_KEY='replace-with-a-secret-from-your-secret-store'
```

The default configuration file is:

```text
~/.config/worktree-review/config.yaml
```

When `XDG_CONFIG_HOME` is set, replace `~/.config` with its value. For
example, `XDG_CONFIG_HOME=/etc/xdg` makes the default path
`/etc/xdg/worktree-review/config.yaml`.

Use `--config PATH` to select another trusted configuration file:

```bash
worktree-review review --config /secure/worktree-review/config.yaml
```

The resolved configuration path must be outside the reviewed worktree,
including after symlink resolution. A configuration file inside the repository
is rejected with exit code `3`.

### Minimal remote configuration

The normal configuration only needs the provider, credential, and model you want
to use:

```yaml
provider: anthropic
key: ${ANTHROPIC_API_KEY}
model: claude-sonnet-4-5
```

`provider: openai` works the same way. The standard endpoint is selected when
`url` is omitted; add `url` for an approved OpenAI-compatible or other custom
endpoint. `model` is optional and falls back to the built-in provider default.
`key` may be a literal secret in a trusted file, but an environment reference
such as `${ANTHROPIC_API_KEY}` is preferred.

### Local CLI provider and adapters

Instead of a remote provider, configure a local executable:

```yaml
provider: local-cli
command:
  - /usr/local/bin/my-review-provider
```

Each list item is one argument. Add command-line flags as additional list items;
shell pipelines, substitutions, and redirections are not supported. The command
is started without a shell. By default it uses the `worktree-json` adapter and
receives one JSON object on stdin:

```json
{
  "system": "...",
  "user": "...",
  "response_schema": {"...": "..."},
  "dimension_id": "correctness",
  "max_output_tokens": 4096
}
```

It must write one `dimension-findings.v1` JSON object to stdout, for example
`{"findings": []}`, and exit with status `0`.

Existing commands that accept a prompt on stdin can use a product adapter without
a project-specific wrapper:

```yaml
provider: local-cli
command:
  - claude
  - --print
adapter: prompt-text-json
```

The `prompt-json` adapter sends the rendered system/user prompt to stdin and
expects one JSON object on stdout. `prompt-text-json` also extracts one JSON
object from a fenced or lightly decorated response. Neither adapter converts
arbitrary prose into reliable findings; the command must still be instructed or
configured to return the `dimension-findings.v1` shape. Use `worktree-json` for a
custom wrapper that wants the response schema and dimension metadata as fields.

You may add local-command disclosure metadata when the command delegates to a
provider or service:

```yaml
data_destination: "Company review gateway"
known_retention: "Retained according to the gateway policy."
```

If omitted, Worktree Review discloses conservative command-defined defaults. A
local executable is not proof that it avoids network access or retention. The
CLI explicitly says that review content is handed to the configured command and
prints a non-secret configuration fingerprint; it does not print command
arguments in the transmission disclosure. Local tools may not report token
usage, so the result can show unknown usage and cost.

### Configuration-derived Compute Policy

`--compute-policy PATH` remains available for deployments that need to control
model, the per-call output limit, budget, token prices, retention text, and
transmission consent directly. It cannot be combined with `--config`. The full
advanced schema and example are in
[examples/compute-policy.yaml](examples/compute-policy.yaml). The normal user
configuration above derives safe operational defaults and is the preferred
starting point.

### Review Policy

Review Policy controls what is reviewed and which verified findings block the
gate. The document schema is `worktree-review.review-policy/v1`.

You do not need to provide one. When `--policy` is omitted, the CLI uses the
trusted built-in policy: `correctness` and `security` are required, `critical`
and `major` findings block from `supported` evidence upward, and `AGENTS.md` and
`CLAUDE.md` are optional context. Use `--policy PATH` only when you need a
different trusted review standard.

Custom policy example:

```yaml
schema: worktree-review.review-policy/v1
version: 0.1.0
required_dimensions:
  - correctness
  - security
blocking_severities:
  - critical
  - major
minimum_blocking_evidence_band: supported
context:
  max_file_bytes: 1048576
  excluded_globs: []
  mandatory_globs: []
  optional_globs:
    - AGENTS.md
    - CLAUDE.md
```

Fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | Must be `worktree-review.review-policy/v1`. |
| `version` | yes | Semantic version recorded in the Request Key and Review Identity. |
| `required_dimensions` | yes | One or more unique dimension IDs. |
| `blocking_severities` | no | Severities that can block. Defaults to `critical` and `major`. |
| `minimum_blocking_evidence_band` | no | Minimum evidence for a blocking finding. Defaults to `supported`. |
| `context` | no | File-size and glob rules for gathered context. |

The built-in dimension prompts are:

- `correctness`: functional defects, contract violations, regressions, and edge cases.
- `security`: authorization, injection, secret exposure, and related defects.
- `performance`: material performance or resource-usage failures.
- `architecture`: architectural inconsistencies and layering violations.
- `maintainability`: concrete maintainability defects.
- `style`: style issues that the policy treats as findings.

Dimension IDs are strings, so a custom ID is accepted and receives a generic
dimension prompt. Use the built-in IDs when their focus matches the review you
want.

Context rules:

- The merge-candidate diff is mandatory context.
- In-scope changed paths are mandatory context unless excluded.
- `mandatory_globs` adds files that must exist and be reviewable. A missing,
  binary, too-large, invalid-UTF-8, or Git LFS pointer file makes required
  coverage incomplete and the gate `Error`.
- `optional_globs` adds files when present. Missing optional files are disclosed
  but do not by themselves make coverage incomplete. `AGENTS.md` and
  `CLAUDE.md` are optional by default.
- `excluded_globs` removes matching paths from review context. Exclusion takes
  precedence over additional mandatory or optional matching.
- `max_file_bytes` applies to gathered files and the merge-candidate diff. It
  defaults to `1048576` bytes.

Repository instruction files are context data, not policy and not trusted
instructions. A model's self-declared `verified` evidence is not accepted as
independent verification; evidence is checked against the captured Review
Worktree or its declared gathered source before it can affect the gate.

### Built-in prompt hierarchy

The built-in prompts are visible in the source tree under
`src/worktree_review/prompts/` and are included in the installed package as
trusted resources, never loaded from the reviewed repository:

```text
src/worktree_review/prompts/
├── 00-product/role.md
├── 10-safety/untrusted-content.md
├── 20-review/evidence.md
├── 30-dimensions/
│   ├── default.md
│   ├── correctness.md
│   ├── security.md
│   ├── performance.md
│   ├── architecture.md
│   ├── maintainability.md
│   └── style.md
└── 40-output/structured-findings.md
```

Each dimension prompt is assembled in this order:

1. Product role and exact merge-candidate scope.
2. Untrusted-content and tool-safety boundary.
3. Evidence and provenance requirements.
4. The selected dimension's focus.
5. Structured findings output requirements.

These are product-owned prompt layers, not repository instructions. Inspect the
effective hierarchy for a dimension directly from an installed CLI:

```bash
worktree-review prompts --dimension security
```

The first stage does not yet provide a user prompt editor or load prompt
overrides from the reviewed repository.

### Advanced Compute Policy

Compute Policy controls the provider, model, per-call output limit, transmission
disclosure, and (for advanced deployments) per-review budget. The document schema is
`worktree-review.compute-policy/v1`.

Example for Anthropic:

```yaml
schema: worktree-review.compute-policy/v1
version: 0.1.0
provider: anthropic
model: claude-sonnet-4-5
max_output_tokens_per_call: 8192
max_budget_usd: 2.00
allow_start_under_uncertain_price: false
permit_remote_transmission: true
input_usd_per_million_tokens: 3
output_usd_per_million_tokens: 15
data_destination: https://api.anthropic.com
known_retention: "Set this to the retention terms approved for your deployment."
```

Fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | Must be `worktree-review.compute-policy/v1`. |
| `version` | yes | Semantic version recorded on the Attempt. |
| `provider` | yes | `anthropic` or `openai`. Local commands belong in normal `--config`. |
| `model` | yes | Model identifier passed to the selected provider SDK. |
| `max_output_tokens_per_call` | no | Hard maximum output requested for each provider call. Defaults to `8192` in advanced policy. |
| `max_budget_usd` | yes | Maximum configured budget for one review. |
| `allow_start_under_uncertain_price` | no | Whether to start when a price estimate cannot be calculated. Defaults to `false`. |
| `permit_remote_transmission` | no | Explicit consent to send review context to the provider. Defaults to `false`. |
| `input_usd_per_million_tokens` | no | Input price used for estimates and cost disclosure. |
| `output_usd_per_million_tokens` | no | Output price used for estimates and cost disclosure. |
| `data_destination` | yes | Human-readable destination disclosed before transmission. |
| `known_retention` | yes | Human-readable retention information disclosed with the result. |

For a live CLI review using `--compute-policy`, set
`permit_remote_transmission: true` only after the destination and retention are
approved. If it is false, the CLI refuses the invocation before making a
provider call and exits `3`. The minimal `--config` form treats a configured
remote provider/key or local command as explicit consent to hand content to the
selected provider, while still disclosing that a local command may make its own
network requests. The standard remote endpoint is used when URL is omitted.

For advanced policy, `data_destination` is disclosure metadata; it does not
configure a custom API endpoint. The selected provider SDK uses its normal
endpoint. The minimal `--config` form uses its optional `url` as the actual
provider endpoint. `known_retention` is displayed as configured policy text and
is not independently verified by the CLI.

When `--compute-policy` is used, the CLI reads remote credentials from the
environment, not from that YAML:

| Compute Policy `provider` | Environment variable |
| --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |

For example:

```bash
export ANTHROPIC_API_KEY='replace-with-a-secret-from-your-secret-store'
```

Do not commit a key. A minimal `--config` file may contain a literal key only
when the file is protected and outside the reviewed worktree; an environment
reference is preferred. A missing environment variable referenced by `--config`
is an invalid configuration and exits `3`; a missing environment key used by
the advanced `--compute-policy` path makes the review `Error` with exit code `2`.

Normal `--config` compute behavior:

- The CLI performs a pre-flight input-token estimate for every required dimension
  before starting provider calls. It does not predict a dollar cost or impose a
  Worktree Review dollar budget on this path.
- Before calls begin, stderr reports the number of model calls, estimated input
  tokens, and the maximum output per call. The normal maximum is `4096` tokens.
- After completion, measured provider usage is shown when available. Cost is
  shown only when a provider or advanced pricing policy supplies it; otherwise
  the result says to check the provider account billing.
- Provider account controls remain the source of truth for real spend. The hard
  per-call output limit controls the size of each normal request.

Advanced `--compute-policy` budget behavior:

- The CLI estimates every required dimension before starting provider calls.
- Configure both input and output prices when you want a priced estimate. If a
  needed price is absent and `allow_start_under_uncertain_price` is false, the
  review does not start.
- Required dimensions run sequentially so measured usage can stop later calls
  when the remaining budget cannot cover their estimate.
- Unknown prices can be allowed explicitly, but the result may report unknown
  cost. This setting does not make the cost known or authorize silent price
  assumptions.

## Review sources

Run the command from the repository, or pass `--repository PATH`. The default
repository is the current directory.

The target is the commit into which the proposed source is merged. The
proposed source is what Worktree Review captures and reviews.

| Invocation | Target | Proposed source | Conditions |
| --- | --- | --- | --- |
| no source flags | `HEAD` | Current worktree snapshot | Default. |
| `--target REF` | `REF` | Current worktree snapshot | Includes current changes. |
| `--commits N` | `HEAD~N` | Current worktree snapshot | Reviews the last `N` commits plus current changes. Cannot combine with `--target` or `--proposed`. |
| `--proposed REF` | `HEAD` unless `--target` is supplied | Explicit committed ref | Worktree must be clean. Cannot combine with `--commits`. |

Current-worktree snapshots include:

- the current bytes of tracked files, including staged and unstaged changes;
- non-ignored untracked files;
- tracked file additions, deletions, mode changes, and symlinks.

Ignored untracked files are not included. The snapshot is captured once before
the pipeline starts, and Worktree Review does not modify the user's index or
worktree. A clean worktree means there are no current changes; with the default
source, the proposed head then resolves to the current `HEAD`.

Examples:

Review the current worktree against `HEAD`:

```bash
worktree-review review \
  --config ~/.config/worktree-review/config.yaml
```

Review the current worktree as it would merge into `origin/main`:

```bash
worktree-review review \
  --repository /path/to/repository \
  --target origin/main \
  --config /secure/worktree-review/config.yaml
```

Review the last three commits plus uncommitted current changes:

```bash
worktree-review review \
  --commits 3 \
  --config /secure/worktree-review/config.yaml
```

Review an explicit committed branch on a clean worktree:

```bash
git status --short
worktree-review review \
  --target main \
  --proposed feature/payment-fix \
  --config /secure/worktree-review/config.yaml
```

If the worktree is dirty, omit `--proposed` to review the current snapshot.

## Output and exit codes

Human-readable output is written to stdout by default:

```bash
worktree-review review \
  --config /secure/worktree-review/config.yaml
```

Use `--format json` for the versioned
`worktree-review.cli.result/v1` document:

```bash
worktree-review review \
  --format json \
  --config /secure/worktree-review/config.yaml \
  > review-result.json
```

The provider-handoff disclosure, call plan, and non-authoritative progress lines
are printed to stderr before and during provider calls, so the redirected stdout
remains JSON. Do not discard stderr if you need to audit the provider, model,
destination, retention, local configuration fingerprint, planned token limit, or
current stage/dimension.

Both output formats expose the Attempt ID, Request Key, source and immutable
head, stage outcomes, dimension outcomes, findings, draft findings, coverage,
usage, call plan, policy versions, and Compute Policy disclosure. A successful merge
construction also exposes the Merge Candidate Identity and Review Identity.

The local CLI uses these process exit codes:

| Code | State | Meaning |
| ---: | --- | --- |
| `0` | `Passed` | Required dimensions and coverage completed, with no unresolved blocking finding. |
| `1` | `Blocked` | At least one verified/supported finding blocks under Review Policy. |
| `2` | `Error` | The review could not complete or a provider/budget/pipeline stage failed. |
| `3` | invalid invocation | Flags, refs, policy paths, Git version, transmission consent, or the worktree snapshot are invalid or unrepresentable. |

The CLI never emits `Passed with bypass`. Draft findings are visible for
diagnosis but are not formal findings and cannot produce `Passed` or `Blocked`.
An incomplete dimension, incomplete required coverage, or failed finding
verification keeps the gate at `Error`.

## Typical troubleshooting

### Configuration or policy file not found

Pass `--config PATH`, or create `config.yaml` in the default config directory.
If using a custom Review Policy or advanced Compute Policy, pass its matching
flag explicitly. Check `XDG_CONFIG_HOME` if the CLI is looking in an unexpected
location.

### Policy is inside the repository

Move it to a trusted user or deployment directory. Repository files, including
`AGENTS.md` and `CLAUDE.md`, cannot change Review Policy or Compute Policy.

### Provider handoff is refused

Review the disclosure printed by the CLI. For the minimal config, a configured
remote provider/key or local command is the explicit consent to hand content to
the selected provider. For a local command, inspect the command, adapter,
destination, and retention metadata because Worktree Review cannot prove whether
the command makes network requests. For an advanced Compute Policy, set
`permit_remote_transmission: true` only when the provider, destination, and
retention are approved.

### Provider authentication fails

For a remote provider, check that `provider`, optional URL, and model match the
intended SDK and that the configured key is available. The key is read only when
the selected provider is built. For a local provider, check that every command
array item is present and executable, and that the selected adapter matches the
command's stdin/stdout behavior. Non-zero exit and malformed-output errors
include bounded, control-escaped child stderr/stdout diagnostics.

### Advanced budget pre-flight refuses to start

This applies only to `--compute-policy`. Increase `max_budget_usd`, configure
both token prices, or explicitly decide whether uncertain pricing may start with
`allow_start_under_uncertain_price: true`. The normal `--config` path has no
Worktree Review dollar budget; review the provider account limits instead.

### Explicit proposed ref is rejected

`--proposed REF` is for a committed source and requires a clean worktree. To
include current changes, remove `--proposed`. To inspect a commit range plus
current changes, use `--commits N`.

### Merge or snapshot construction fails

The CLI returns `Error` for merge conflicts and returns invalid invocation for
an unrepresentable worktree snapshot. Resolve the conflict or unsupported
filesystem entry, then run the review again. The CLI does not execute or modify
the proposed code for this purpose.

### The result says `Error`

Inspect `stage_outcomes`, `dimension_outcomes`, `coverage`, `error_detail`, and
the terminal `Error:` line. A partial result may contain verified findings and
visible draft findings, but it is not a passing or blocking gate decision.

## Server status

The server entry point requires the server extra:

```bash
uv sync --extra server
```

The current development runtime recognizes these deployment variables:

- `WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET`
- `WORKTREE_REVIEW_DATABASE_URL`
- `WORKTREE_REVIEW_GITHUB_TOKEN`
- `WORKTREE_REVIEW_REVIEW_POLICY_PATH`
- `WORKTREE_REVIEW_GITHUB_API_URL` (optional; defaults to `https://api.github.com`)

`GET /healthz` is available as a liveness endpoint. The webhook and retry state
pieces are present, but the embedded review worker and end-to-end shared
pipeline publication are still incomplete. Treat the local CLI above as the
current supported user workflow; finish the GitHub worker before deploying the
server as a review service.

## Further reading

- [User configuration example](config.example.yaml)
- [Review Policy example](examples/review-policy.yaml)
- [Advanced Compute Policy example](examples/compute-policy.yaml)
- [Product requirements](docs/PRD.md)
- [Technical design](docs/TECH-DESIGN.md)
