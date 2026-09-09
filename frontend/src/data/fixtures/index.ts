import type { ReviewRunView } from '../../domain/review.ts'
import { createPlaceholderReviewRun } from './placeholders.ts'

export const FIXTURE_CASE_KEYS = ['passed', 'blocked', 'error_merge_conflict'] as const

export type FixtureCaseKey = (typeof FIXTURE_CASE_KEYS)[number]

/** Frozen Blocked demo Attempt ID. Do not treat Case Keys as Attempt IDs. */
export const BLOCKED_DEMO_ATTEMPT_ID = 'attempt_01JY8R7F2W'

export const passedCase: ReviewRunView = createPlaceholderReviewRun({
  attemptId: 'attempt_passed_placeholder',
  gateState: 'passed',
  sourceKind: 'local-worktree',
})

export const blockedCase: ReviewRunView = createPlaceholderReviewRun({
  attemptId: BLOCKED_DEMO_ATTEMPT_ID,
  gateState: 'blocked',
  sourceKind: 'github-pull-request',
})

export const errorMergeConflictCase: ReviewRunView = createPlaceholderReviewRun({
  attemptId: 'attempt_error_merge_conflict_placeholder',
  gateState: 'error',
  sourceKind: 'local-committed-ref',
})

const fixtureCases: Record<FixtureCaseKey, ReviewRunView> = {
  passed: passedCase,
  blocked: blockedCase,
  error_merge_conflict: errorMergeConflictCase,
}

export function getFixtureCase(caseKey: FixtureCaseKey): ReviewRunView {
  return fixtureCases[caseKey]
}
