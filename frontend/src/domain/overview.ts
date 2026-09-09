import type {
  FindingSeverity,
  GateState,
  ProviderHealthView,
  ReviewSummaryView,
} from './review.ts'

export interface OverviewStatsView {
  attemptCount: number
  passedCount: number
  blockedCount: number
  errorCount: number
  gatePassRate: number | null
  errorRate: number | null
  averageDurationMs: number | null
  knownCostUsd: number
  unknownCostRecordCount: number
  knownInputTokens: number
  knownOutputTokens: number
}

export interface OverviewTrendPointView {
  date: string
  passed: number
  blocked: number
  error: number
  inProgress: number
}

export interface FindingSeverityCountView {
  severity: FindingSeverity
  count: number
}

export interface DimensionHealthView {
  dimensionId: string
  completedCount: number
  failedCount: number
  averageElapsedMs: number | null
}

export interface PolicyUsageView {
  reviewPolicyVersion: string
  reviewCount: number
  blockedCount: number
  errorCount: number
}

export type SessionInsightConnectionState =
  | 'connected'
  | 'disconnected'
  | 'incompatible'
  | 'disabled'

export interface SessionInsightStatusView {
  state: SessionInsightConnectionState
  currentAttemptId: string | null
  childSessionCount: number
  lastProbeAt: string | null
}

export interface OverviewView {
  attention: ReviewSummaryView[]
  active: ReviewSummaryView[]
  recent: ReviewSummaryView[]
  stats: OverviewStatsView
  gateTrend: OverviewTrendPointView[]
  findingSeverity: FindingSeverityCountView[]
  dimensionHealth: DimensionHealthView[]
  policyUsage: PolicyUsageView[]
  providerHealth: ProviderHealthView[]
  sessionInsight: SessionInsightStatusView
}

export interface FixtureCaseDescriptor {
  caseKey: 'passed' | 'blocked' | 'error_merge_conflict'
  attemptId: string
  gateState: GateState
  title: string
}
