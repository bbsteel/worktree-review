import { describe, expect, it } from 'vitest'
import {
  BLOCKED_DEMO_ATTEMPT_ID,
  blockedCase,
  errorMergeConflictCase,
  FIXTURE_CASE_KEYS,
  getFixtureCase,
  passedCase,
} from './index.ts'

describe('stable fixture export names', () => {
  it('exports the three frozen case keys', () => {
    expect(FIXTURE_CASE_KEYS).toEqual(['passed', 'blocked', 'error_merge_conflict'])
  })

  it('keeps case keys distinct from attempt IDs', () => {
    expect(BLOCKED_DEMO_ATTEMPT_ID).toBe('attempt_01JY8R7F2W')
    expect(blockedCase.attemptId).toBe(BLOCKED_DEMO_ATTEMPT_ID)
    expect(FIXTURE_CASE_KEYS.includes(blockedCase.attemptId as never)).toBe(false)
  })

  it('exports passed, blocked, and error_merge_conflict cases', () => {
    expect(passedCase.gateState).toBe('passed')
    expect(blockedCase.gateState).toBe('blocked')
    expect(errorMergeConflictCase.gateState).toBe('error')
    expect(getFixtureCase('blocked').attemptId).toBe(BLOCKED_DEMO_ATTEMPT_ID)
  })

  it('does not collapse lifecycle axes into one status field', () => {
    expect(blockedCase.runStatus).toBe('completed')
    expect(blockedCase.gateState).toBe('blocked')
    expect(blockedCase.authority).toBe('authoritative')
    expect(blockedCase.publicationStatus).toBe('not_applicable')
    expect(blockedCase.bypassState).toBe('none')
  })
})
