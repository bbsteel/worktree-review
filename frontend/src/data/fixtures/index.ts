import type { ReviewRunView } from '../../domain/review.ts'
import { blockedCase } from './blocked.ts'
import {
  BLOCKED_DEMO_ATTEMPT_ID,
  ERROR_DEMO_ATTEMPT_ID,
  MOCK_DATA_BADGE,
  PASSED_DEMO_ATTEMPT_ID,
  type FixtureCaseKey,
} from './constants.ts'
import { errorMergeConflictCase } from './error-merge-conflict.ts'
import { passedCase } from './passed.ts'

export {
  BLOCKED_COST_USD,
  BLOCKED_DEMO_ATTEMPT_ID,
  BLOCKED_DURATION_MS,
  ERROR_DEMO_ATTEMPT_ID,
  FIXTURE_CASE_KEYS,
  FIXTURE_CLOCK,
  LONG_EVIDENCE_PATH,
  LONG_HASH,
  MERGE_CONFLICT_ERROR,
  MOCK_DATA_BADGE,
  PASSED_COST_USD,
  PASSED_DEMO_ATTEMPT_ID,
  PASSED_DURATION_MS,
  type FixtureCaseKey,
} from './constants.ts'
export { blockedCase } from './blocked.ts'
export { errorMergeConflictCase } from './error-merge-conflict.ts'
export { passedCase } from './passed.ts'
export { buildOverview, MOCK_GATE_TREND } from './overview.ts'

const fixtureCases: Record<FixtureCaseKey, ReviewRunView> = {
  passed: passedCase,
  blocked: blockedCase,
  error_merge_conflict: errorMergeConflictCase,
}

const fixturesByAttemptId: Record<string, ReviewRunView> = {
  [PASSED_DEMO_ATTEMPT_ID]: passedCase,
  [BLOCKED_DEMO_ATTEMPT_ID]: blockedCase,
  [ERROR_DEMO_ATTEMPT_ID]: errorMergeConflictCase,
}

export function getFixtureCase(caseKey: FixtureCaseKey): ReviewRunView {
  return fixtureCases[caseKey]
}

export function getFixtureByAttemptId(attemptId: string): ReviewRunView | null {
  return fixturesByAttemptId[attemptId] ?? null
}

export function listFixtureCases(): Array<{
  caseKey: FixtureCaseKey
  attemptId: string
  gateState: ReviewRunView['gateState']
  title: string
  badge: typeof MOCK_DATA_BADGE
}> {
  return [
    {
      caseKey: 'passed',
      attemptId: passedCase.attemptId,
      gateState: passedCase.gateState,
      title: 'Passed local worktree',
      badge: MOCK_DATA_BADGE,
    },
    {
      caseKey: 'blocked',
      attemptId: blockedCase.attemptId,
      gateState: blockedCase.gateState,
      title: 'Blocked GitHub pull request',
      badge: MOCK_DATA_BADGE,
    },
    {
      caseKey: 'error_merge_conflict',
      attemptId: errorMergeConflictCase.attemptId,
      gateState: errorMergeConflictCase.gateState,
      title: 'Error merge conflict',
      badge: MOCK_DATA_BADGE,
    },
  ]
}
