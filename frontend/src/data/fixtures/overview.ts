import type { OverviewStatsView, OverviewTrendPointView, OverviewView } from '../../domain/overview.ts'
import { blockedCase } from './blocked.ts'
import { errorMergeConflictCase } from './error-merge-conflict.ts'
import { passedCase } from './passed.ts'
import { openaiProviderHealth } from './shared.ts'

export const MOCK_GATE_TREND: OverviewTrendPointView[] = [
  { date: '2026-09-03', passed: 2, blocked: 1, error: 0, inProgress: 0 },
  { date: '2026-09-04', passed: 3, blocked: 0, error: 1, inProgress: 0 },
  { date: '2026-09-05', passed: 1, blocked: 2, error: 0, inProgress: 0 },
  { date: '2026-09-06', passed: 4, blocked: 1, error: 0, inProgress: 0 },
  { date: '2026-09-07', passed: 2, blocked: 1, error: 1, inProgress: 0 },
  { date: '2026-09-08', passed: 3, blocked: 1, error: 0, inProgress: 0 },
  { date: '2026-09-09', passed: 1, blocked: 1, error: 1, inProgress: 0 },
]

function statsFromTrend(trend: OverviewTrendPointView[]): OverviewStatsView {
  const passedCount = trend.reduce((sum, point) => sum + point.passed, 0)
  const blockedCount = trend.reduce((sum, point) => sum + point.blocked, 0)
  const errorCount = trend.reduce((sum, point) => sum + point.error, 0)
  const inProgressCount = trend.reduce((sum, point) => sum + point.inProgress, 0)
  const attemptCount = passedCount + blockedCount + errorCount + inProgressCount
  const decidedCount = passedCount + blockedCount
  const terminalCount = passedCount + blockedCount + errorCount
  const detailedDurations = [passedCase, blockedCase, errorMergeConflictCase]
    .map((run) => run.summary.durationMs)
    .filter((value): value is number => value !== null)
  const knownCosts = [passedCase, blockedCase]
    .map((run) => run.summary.costUsd)
    .filter((value): value is number => value !== null)

  return {
    attemptCount,
    passedCount,
    blockedCount,
    errorCount,
    gatePassRate: decidedCount === 0 ? null : passedCount / decidedCount,
    errorRate: terminalCount === 0 ? null : errorCount / terminalCount,
    averageDurationMs:
      detailedDurations.length === 0
        ? null
        : detailedDurations.reduce((sum, value) => sum + value, 0) / detailedDurations.length,
    knownCostUsd: knownCosts.reduce((sum, value) => sum + value, 0),
    unknownCostRecordCount: errorMergeConflictCase.usage.unknownCostRecordCount,
    knownInputTokens: (passedCase.usage.inputTokens ?? 0) + (blockedCase.usage.inputTokens ?? 0),
    knownOutputTokens: (passedCase.usage.outputTokens ?? 0) + (blockedCase.usage.outputTokens ?? 0),
  }
}

export function buildOverview(): OverviewView {
  const runs = [blockedCase, errorMergeConflictCase, passedCase]
  return {
    attention: [blockedCase.summary, errorMergeConflictCase.summary],
    active: [],
    recent: runs.map((run) => run.summary),
    stats: statsFromTrend(MOCK_GATE_TREND),
    gateTrend: MOCK_GATE_TREND,
    findingSeverity: [
      { severity: 'critical', count: 0 },
      { severity: 'major', count: 1 },
      { severity: 'minor', count: 1 },
      { severity: 'suggestion', count: 1 },
    ],
    dimensionHealth: [
      { dimensionId: 'security', completedCount: 2, failedCount: 0, averageElapsedMs: 33_900 },
      { dimensionId: 'correctness', completedCount: 2, failedCount: 0, averageElapsedMs: 22_600 },
      { dimensionId: 'architecture', completedCount: 2, failedCount: 0, averageElapsedMs: 19_200 },
      { dimensionId: 'maintainability', completedCount: 2, failedCount: 0, averageElapsedMs: 16_700 },
    ],
    policyUsage: [
      {
        reviewPolicyVersion: '1.3.0',
        reviewCount: MOCK_GATE_TREND.reduce(
          (sum, point) => sum + point.passed + point.blocked + point.error,
          0,
        ),
        blockedCount: MOCK_GATE_TREND.reduce((sum, point) => sum + point.blocked, 0),
        errorCount: MOCK_GATE_TREND.reduce((sum, point) => sum + point.error, 0),
      },
    ],
    providerHealth: [openaiProviderHealth],
    sessionInsight: {
      state: 'disconnected',
      currentAttemptId: null,
      childSessionCount: 0,
      lastProbeAt: null,
    },
  }
}
