/**
 * Frozen G0 frontend View Model.
 * Field names use camelCase in TypeScript; later HTTP DTOs may use snake_case.
 * Do not collapse run/gate/authority/publication/bypass into a single status.
 */

export type RunStatus =
  | 'queued'
  | 'preparing'
  | 'running'
  | 'completed'
  | 'failed'
  | 'interrupted'

export type GateState =
  | 'awaiting_review'
  | 'in_progress'
  | 'passed'
  | 'passed_with_bypass'
  | 'blocked'
  | 'error'

export type Authority =
  | 'local_non_authoritative'
  | 'authoritative'
  | 'superseded'
  | 'audit_only'

export type PublicationStatus =
  | 'not_applicable'
  | 'queued'
  | 'in_progress'
  | 'published'
  | 'failed'
  /** Terminal, never retried: a newer attempt took authority. */
  | 'superseded'

export type BypassState = 'none' | 'active' | 'invalidated'

export type FindingSeverity = 'critical' | 'major' | 'minor' | 'suggestion'

export type EvidenceBand = 'supported' | 'insufficient'

export type DimensionStatus = 'not-started' | 'running' | 'completed' | 'failed'

export type CoverageCategory =
  | 'reviewed'
  | 'mandatory-missing'
  | 'optional-missing'
  | 'excluded'
  | 'unreviewable'

export type RequiredCoverageState = 'complete' | 'incomplete'

export type ProviderHealthStatus = 'healthy' | 'last_call_failed' | 'not_tested'

export type LocalReviewSourceKind =
  | 'local-worktree'
  | 'local-recent-commits'
  | 'local-committed-ref'

export type ReviewSourceKind = LocalReviewSourceKind | 'github-pull-request'

export interface ReviewActionCapabilityView {
  visible: boolean
  enabled: boolean
  disabledReason: string | null
}

export interface AvailableReviewActionsView {
  retry: ReviewActionCapabilityView
  bypass: ReviewActionCapabilityView
  openCheck: ReviewActionCapabilityView
  openSessionInsight: ReviewActionCapabilityView
}

export interface LocalReviewSourceView {
  kind: LocalReviewSourceKind
  repositoryDisplayName: string
  worktreeLabel: string | null
  targetRef: string | null
  proposedRef: string | null
  snapshotSha: string | null
}

export interface GitHubPullRequestSourceView {
  kind: 'github-pull-request'
  repositoryFullName: string
  pullRequestNumber: number
  pullRequestTitle: string
  authorLogin: string
  proposedBranch: string
  targetBranch: string
  commitSha: string
  checkUrl: string | null
}

export type ReviewSourceView = LocalReviewSourceView | GitHubPullRequestSourceView

export interface ReviewSummaryView {
  attemptId: string
  repositoryDisplayName: string
  source: ReviewSourceView
  runStatus: RunStatus
  gateState: GateState
  authority: Authority
  publicationStatus: PublicationStatus
  bypassState: BypassState
  findingCount: number
  highestSeverity: FindingSeverity | null
  durationMs: number | null
  costUsd: number | null
  costUnknown: boolean
  provider: string
  model: string
  createdAt: string
  completedAt: string | null
}

export interface GateDecisionView {
  gateState: GateState
  blockingFingerprints: string[]
  summary: string
  requiredCoverageComplete: boolean
  /** Blocking fingerprints without an active bypass (P3). Absent for older DTOs. */
  remainingBlockingFingerprints?: string[]
}

/** One per-finding risk acceptance as projected read-only onto the Detail DTO (P3 §8.2). */
export interface BypassRecordView {
  status: 'active' | 'invalidated'
  actorId: number | null
  actorLogin: string
  reason: string
  createdAt: string
  invalidationReason: string | null
}

export type CheckSyncStatus =
  | 'queued'
  | 'in_progress'
  | 'published'
  | 'failed'
  | 'superseded'
  | 'not_applicable'

export interface EvidenceSpanView {
  path: string
  startLine: number
  endLine: number
  source: string
  snapshotIdentity: string
  changeKind: string
  quotedText: string
}

export interface ReviewFindingView {
  fingerprint: string
  severity: FindingSeverity
  evidenceBand: EvidenceBand
  dimensionId: string
  problemStatement: string
  expectedImpact: string
  repairGuidance: string
  evidenceSpans: EvidenceSpanView[]
  blocking: boolean
  /** Present on GitHub Detail DTOs when the attempt has bypass history (P3). */
  bypassRecord?: BypassRecordView | null
}

export interface CoverageFileView {
  path: string
  category: CoverageCategory
  reason: string | null
  rule: string | null
}

export interface CoverageView {
  requiredCoverage: RequiredCoverageState
  reviewedCount: number
  excludedCount: number
  missingCount: number
  files: CoverageFileView[]
}

export interface ReviewDimensionView {
  dimensionId: string
  status: DimensionStatus
  elapsedMs: number | null
  findingCount: number
  blockingFindingCount: number
}

export interface ReviewAttemptView {
  attemptId: string
  authority: Authority
  gateState: GateState
  trigger: string
  provider: string
  model: string
  reviewPolicyVersion: string
  computePolicyVersion: string
  tokenCount: number | null
  costUsd: number | null
  costUnknown: boolean
  startedAt: string
  durationMs: number | null
}

export interface ReviewIdentityView {
  reviewRequestKey: string
  sourceRepository: string
  targetRef: string
  targetHeadOid: string | null
  proposedSource: string
  proposedHeadOid: string | null
  mergeTreeOid: string | null
  reviewIdentity: string | null
  identityUnavailableReason: string | null
}

export interface PolicySnapshotView {
  reviewPolicyName: string
  reviewPolicyVersion: string
  reviewPolicySha256: string
  computePolicyName: string
  computePolicyVersion: string
  computePolicySha256: string
  dataDestination: string
  retentionDisclosure: string
  providerConfigurationFingerprint: string | null
}

export interface ReviewUsageCallView {
  ordinal: number | null
  dimensionId: string | null
  provider: string
  model: string
  elapsedMs: number | null
  usageKind: string
  inputTokens: number | null
  outputTokens: number | null
  costUsd: number | null
  costUnknown: boolean
}

export interface ReviewUsageView {
  estimatedCostUsd: number | null
  actualCostUsd: number | null
  costUnknown: boolean
  unknownCostRecordCount: number
  inputTokens: number | null
  outputTokens: number | null
  calls: ReviewUsageCallView[]
}

export interface ProviderHealthView {
  profileName: string
  status: ProviderHealthStatus
  observedAt: string | null
}

export const PIPELINE_STAGE_ORDER = [
  'derive-identity',
  'construct-merge',
  'prepare-review-worktree',
  'gather-context',
  'run-dimensions',
  'verify-dedup',
  'check-completeness',
  'evaluate-gate',
  'publish',
] as const

export type PipelineStageName = (typeof PIPELINE_STAGE_ORDER)[number]

export type PipelineStageStatus = 'not-started' | 'running' | 'completed' | 'failed'

export interface PipelineStageView {
  stage: PipelineStageName
  status: PipelineStageStatus
  elapsedMs: number | null
  safeError: string | null
}

export interface ReviewFailureView {
  stage: PipelineStageName
  category: string
  safeDetail: string
}

export interface ReviewRunView {
  attemptId: string
  runStatus: RunStatus
  gateState: GateState
  authority: Authority
  publicationStatus: PublicationStatus
  bypassState: BypassState
  source: ReviewSourceView
  summary: ReviewSummaryView
  gate: GateDecisionView
  findings: ReviewFindingView[]
  coverage: CoverageView
  dimensions: ReviewDimensionView[]
  pipeline: PipelineStageView[]
  failure: ReviewFailureView | null
  attempts: ReviewAttemptView[]
  identity: ReviewIdentityView
  policies: PolicySnapshotView
  usage: ReviewUsageView
  providerHealth: ProviderHealthView
  availableActions: AvailableReviewActionsView
  /**
   * Server-computed deep link from trusted deployment configuration:
   * <base>#/session/worktree-review/<attempt-id>. Present only when the
   * Session Insight integration is connected.
   */
  sessionInsightDeepLink?: string | null
  /**
   * P3 standing projection (GitHub attempts only): the immutable Core gate,
   * the platform standing decision with its monotonic revision, and the
   * standing Check sync state. Absent on local/legacy DTOs.
   */
  coreGateState?: string | null
  standingGateState?: string | null
  standingRevision?: number | null
  checkSyncStatus?: CheckSyncStatus | null
  /** UI hint only — the server re-authorizes every bypass POST. */
  bypassCapability?: 'available' | 'unavailable'
}
