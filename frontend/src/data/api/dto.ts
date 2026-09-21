/**
 * Wire DTOs for the /api/v1 HTTP contract (design 16).
 *
 * DTO field names are snake_case and mirror the frozen G0 View Model field
 * for field. This file only declares shapes; map-dto.ts validates actual
 * payloads and fails closed on unknown values. Nothing here widens a frozen
 * enum or adds a surface field to Core semantics.
 */

export interface ApiErrorDto {
  error: {
    code: string
    message: string
  }
}

export interface ActionCapabilityDto {
  visible: boolean
  enabled: boolean
  disabled_reason: string | null
}

export interface AvailableActionsDto {
  retry: ActionCapabilityDto
  bypass: ActionCapabilityDto
  open_check: ActionCapabilityDto
  open_session_insight: ActionCapabilityDto
}

export interface LocalSourceDto {
  kind: string
  repository_display_name: string
  worktree_label: string | null
  target_ref: string | null
  proposed_ref: string | null
  snapshot_sha: string | null
}

export interface GitHubSourceDto {
  kind: string
  repository_full_name: string
  pull_request_number: number
  pull_request_title: string
  author_login: string
  proposed_branch: string
  target_branch: string
  commit_sha: string
  check_url: string | null
}

export type ReviewSourceDto = LocalSourceDto | GitHubSourceDto

export interface ReviewSummaryDto {
  attempt_id: string
  repository_display_name: string
  source: ReviewSourceDto
  run_status: string
  gate_state: string
  authority: string
  publication_status: string
  bypass_state: string
  finding_count: number
  highest_severity: string | null
  duration_ms: number | null
  cost_usd: number | null
  cost_unknown: boolean
  provider: string
  model: string
  created_at: string
  completed_at: string | null
}

export interface GateDecisionDto {
  gate_state: string
  blocking_fingerprints: string[]
  summary: string
  required_coverage_complete: boolean
  /** P3: blocking fingerprints without an active bypass; absent on legacy DTOs. */
  remaining_blocking_fingerprints?: string[]
}

export interface EvidenceSpanDto {
  path: string
  start_line: number
  end_line: number
  source: string
  snapshot_identity: string
  change_kind: string
  quoted_text: string
}

export interface FindingDto {
  fingerprint: string
  severity: string
  evidence_band: string
  dimension_id: string
  problem_statement: string
  expected_impact: string
  repair_guidance: string
  evidence_spans: EvidenceSpanDto[]
  blocking: boolean
  /** P3: present on GitHub Detail DTOs when the attempt has bypass history. */
  bypass_record?: BypassRecordDto | null
}

/** P3 §8.2: read-only per-finding risk acceptance projection. */
export interface BypassRecordDto {
  status: string
  actor_id: number | null
  actor_login: string
  reason: string
  created_at: string
  invalidation_reason: string | null
}

export interface CoverageFileDto {
  path: string
  category: string
  reason: string | null
  rule: string | null
}

export interface CoverageDto {
  required_coverage: string
  reviewed_count: number
  excluded_count: number
  missing_count: number
  files: CoverageFileDto[]
}

export interface DimensionDto {
  dimension_id: string
  status: string
  elapsed_ms: number | null
  finding_count: number
  blocking_finding_count: number
}

export interface AttemptDto {
  attempt_id: string
  authority: string
  gate_state: string
  trigger: string
  provider: string
  model: string
  review_policy_version: string
  compute_policy_version: string
  token_count: number | null
  cost_usd: number | null
  cost_unknown: boolean
  started_at: string
  duration_ms: number | null
}

export interface IdentityDto {
  review_request_key: string
  source_repository: string
  target_ref: string
  target_head_oid: string | null
  proposed_source: string
  proposed_head_oid: string | null
  merge_tree_oid: string | null
  review_identity: string | null
  identity_unavailable_reason: string | null
}

export interface PolicySnapshotDto {
  review_policy_name: string
  review_policy_version: string
  review_policy_sha256: string
  compute_policy_name: string
  compute_policy_version: string
  compute_policy_sha256: string
  data_destination: string
  retention_disclosure: string
  provider_configuration_fingerprint: string | null
}

export interface UsageCallDto {
  ordinal: number | null
  dimension_id: string | null
  provider: string
  model: string
  elapsed_ms: number | null
  usage_kind: string
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  cost_unknown: boolean
}

export interface UsageDto {
  estimated_cost_usd: number | null
  actual_cost_usd: number | null
  cost_unknown: boolean
  unknown_cost_record_count: number
  input_tokens: number | null
  output_tokens: number | null
  calls: UsageCallDto[]
}

export interface ProviderHealthDto {
  profile_name: string
  status: string
  observed_at: string | null
}

export interface PipelineStageDto {
  stage: string
  status: string
  elapsed_ms: number | null
  safe_error: string | null
}

export interface FailureDto {
  stage: string
  category: string
  safe_detail: string
}

export interface ReviewRunDto {
  attempt_id: string
  run_status: string
  gate_state: string
  authority: string
  publication_status: string
  bypass_state: string
  source: ReviewSourceDto
  summary: ReviewSummaryDto
  gate: GateDecisionDto
  findings: FindingDto[]
  coverage: CoverageDto
  dimensions: DimensionDto[]
  pipeline: PipelineStageDto[]
  failure: FailureDto | null
  attempts: AttemptDto[]
  identity: IdentityDto
  policies: PolicySnapshotDto
  usage: UsageDto
  provider_health: ProviderHealthDto
  available_actions: AvailableActionsDto
  /** Server-computed Session Insight deep link from trusted deployment config. */
  session_insight_deep_link?: string | null
  /** P3 standing projection (GitHub attempts only); absent on legacy DTOs. */
  core_gate_state?: string | null
  standing_gate_state?: string | null
  standing_revision?: number | null
  check_sync_status?: string | null
  bypass_capability?: string
}

export interface OverviewStatsDto {
  attempt_count: number
  passed_count: number
  blocked_count: number
  error_count: number
  gate_pass_rate: number | null
  error_rate: number | null
  average_duration_ms: number | null
  known_cost_usd: number
  unknown_cost_record_count: number
  known_input_tokens: number
  known_output_tokens: number
}

export interface OverviewTrendPointDto {
  date: string
  passed: number
  blocked: number
  error: number
  in_progress: number
}

export interface FindingSeverityCountDto {
  severity: string
  count: number
}

export interface DimensionHealthDto {
  dimension_id: string
  completed_count: number
  failed_count: number
  average_elapsed_ms: number | null
}

export interface PolicyUsageDto {
  review_policy_version: string
  review_count: number
  blocked_count: number
  error_count: number
}

export interface SessionInsightStatusDto {
  state: string
  current_attempt_id: string | null
  child_session_count: number
  last_probe_at: string | null
}

export interface OverviewDto {
  attention: ReviewSummaryDto[]
  active: ReviewSummaryDto[]
  recent: ReviewSummaryDto[]
  stats: OverviewStatsDto
  gate_trend: OverviewTrendPointDto[]
  finding_severity: FindingSeverityCountDto[]
  dimension_health: DimensionHealthDto[]
  policy_usage: PolicyUsageDto[]
  provider_health: ProviderHealthDto[]
  session_insight: SessionInsightStatusDto
}

export interface ReviewEventDto {
  schema: string
  sequence: number
  occurred_at: string
  attempt_id: string
  surface: string
  event_type: string
  payload: Record<string, unknown>
}

export interface ReviewListDto {
  runs: ReviewSummaryDto[]
  next_cursor: string | null
}

export interface CreateReviewRequestDto {
  repository_id: string
  source:
    | { kind: 'local-worktree'; target_ref?: string }
    | { kind: 'local-recent-commits'; commit_count: number }
    | { kind: 'local-committed-ref'; proposed_ref: string; target_ref?: string }
  review_policy_id: string
  compute_policy_id: string
}

export interface CreateReviewResponseDto {
  attempt_id: string
}

export interface RepositoryDto {
  repository_id: string
  display_name: string
  canonical_root: string
  last_gate_state: string | null
  last_reviewed_at: string | null
}

export interface RepositoryStatusDto {
  repository_id: string
  branch: string
  head_oid: string
  dirty: boolean
  tracked_modifications: number
  untracked_files: number
  accessible: boolean
  identity_drift: boolean
}

export interface RegisterRepositoryRequestDto {
  path: string
  display_name?: string
}

export type CredentialReferenceState = 'configured' | 'missing' | 'invalid_reference' | 'not_applicable'

export interface ProviderProfileDto {
  profile_id: string
  name: string
  provider: string
  endpoint: string | null
  local_cli_adapter: string | null
  local_cli_command: string[] | null
  adapter_label: string | null
  credential_reference: string | null
  credential_state: CredentialReferenceState
  last_used_at: string | null
  health: ProviderHealthDto
  referenced_by_history: boolean
  is_default: boolean
}

export interface SaveProviderProfileRequestDto {
  name: string
  provider: string
  endpoint?: string | null
  credential_reference?: string | null
  local_cli_adapter?: string | null
  local_cli_command?: string[] | null
  adapter_label?: string | null
}

export type ProviderTestKind =
  | 'credential_reference_validation'
  | 'local_cli_executable_check'

export interface ProviderTestResultDto {
  ok: boolean
  /** What was actually verified — never implied to be a live provider call. */
  test_kind?: ProviderTestKind
  detail: string
  tested_at: string
}

export interface RegisterReviewPolicyRequestDto {
  path: string
}

export interface RegisterComputePolicyRequestDto {
  path: string
  provider_profile_id?: string | null
}

export interface ReviewPolicyDto {
  policy_id: string
  name: string
  version: string
  sha256: string
  builtin: boolean
  required_dimensions: string[]
  blocking_severities: string[]
  minimum_blocking_evidence_band: string
  output_language: string
  context_rules: string[]
  mandatory_globs: string[]
  optional_globs: string[]
  excluded_globs: string[]
}

export interface ComputePolicyDto {
  policy_id: string
  name: string
  version: string
  sha256: string
  provider_profile_id: string
  provider_profile_name: string
  provider: string
  model: string
  max_output_tokens_per_call: number
  budget_usd: number | null
  pricing_source: string
  start_with_uncertain_pricing: boolean
  data_destination: string
  known_retention: string
}
