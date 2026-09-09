import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  BLOCKED_COST_USD,
  BLOCKED_DEMO_ATTEMPT_ID,
  BLOCKED_DURATION_MS,
  blockedCase,
  ERROR_DEMO_ATTEMPT_ID,
  errorMergeConflictCase,
  FIXTURE_CASE_KEYS,
  getFixtureCase,
  LONG_EVIDENCE_PATH,
  LONG_HASH,
  MERGE_CONFLICT_ERROR,
  PASSED_DEMO_ATTEMPT_ID,
  passedCase,
} from './index.ts'
import { buildOverview, MOCK_GATE_TREND } from './overview.ts'

describe('stable fixture export names', () => {
  it('exports the three frozen case keys', () => {
    expect(FIXTURE_CASE_KEYS).toEqual(['passed', 'blocked', 'error_merge_conflict'])
  })

  it('keeps case keys distinct from attempt IDs', () => {
    expect(BLOCKED_DEMO_ATTEMPT_ID).toBe('attempt_01JY8R7F2W')
    expect(blockedCase.attemptId).toBe(BLOCKED_DEMO_ATTEMPT_ID)
    expect(passedCase.attemptId).toBe(PASSED_DEMO_ATTEMPT_ID)
    expect(errorMergeConflictCase.attemptId).toBe(ERROR_DEMO_ATTEMPT_ID)
    expect(FIXTURE_CASE_KEYS.includes(blockedCase.attemptId as never)).toBe(false)
    expect(new Set([passedCase.attemptId, blockedCase.attemptId, errorMergeConflictCase.attemptId]).size).toBe(3)
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
    expect(errorMergeConflictCase.runStatus).toBe('failed')
    expect(errorMergeConflictCase.gateState).toBe('error')
  })
})

describe('fixture content', () => {
  it('does not use any in handwritten fixtures', () => {
    const files = ['blocked.ts', 'passed.ts', 'error-merge-conflict.ts', 'overview.ts', 'shared.ts', 'index.ts']
    for (const file of files) {
      const source = readFileSync(path.resolve('src/data/fixtures', file), 'utf8')
      expect(source, file).not.toMatch(/\bany\b/)
    }
  })

  it('uses deterministic blocked cost and duration', () => {
    expect(blockedCase.summary.costUsd).toBe(BLOCKED_COST_USD)
    expect(blockedCase.summary.durationMs).toBe(BLOCKED_DURATION_MS)
    expect(blockedCase.summary.costUnknown).toBe(false)
    expect(blockedCase.policies.reviewPolicyVersion).toBe('1.3.0')
    expect(blockedCase.summary.provider).toBe('openai')
    expect(blockedCase.summary.model).toBe('gpt-5.6')
  })

  it('covers long path, hash, and error text', () => {
    expect(LONG_EVIDENCE_PATH.length).toBeGreaterThan(80)
    expect(LONG_HASH).toHaveLength(64)
    expect(MERGE_CONFLICT_ERROR.length).toBeGreaterThan(200)
    expect(blockedCase.findings[0]?.evidenceSpans[0]?.path).toBe(LONG_EVIDENCE_PATH)
    expect(blockedCase.identity.reviewIdentity).toBe(LONG_HASH)
    expect(errorMergeConflictCase.failure?.safeDetail).toContain(LONG_EVIDENCE_PATH)
  })

  it('does not treat unknown error cost as zero', () => {
    expect(errorMergeConflictCase.summary.costUsd).toBeNull()
    expect(errorMergeConflictCase.summary.costUnknown).toBe(true)
    expect(errorMergeConflictCase.usage.actualCostUsd).toBeNull()
    expect(errorMergeConflictCase.usage.unknownCostRecordCount).toBe(1)
  })

  it('keeps local and GitHub source fields from leaking across kinds', () => {
    expect(passedCase.source.kind).toBe('local-worktree')
    expect(errorMergeConflictCase.source.kind).toBe('local-committed-ref')
    expect(blockedCase.source.kind).toBe('github-pull-request')
    if (blockedCase.source.kind === 'github-pull-request') {
      expect(blockedCase.source.repositoryFullName).toBe('acme/payment-service')
      expect(blockedCase.source.pullRequestNumber).toBe(184)
    }
    expect(passedCase.availableActions.bypass.visible).toBe(false)
    expect(blockedCase.availableActions.bypass.visible).toBe(true)
    expect(blockedCase.availableActions.bypass.enabled).toBe(false)
  })

  it('does not fabricate Review Identity after merge failure', () => {
    expect(errorMergeConflictCase.identity.reviewIdentity).toBeNull()
    expect(errorMergeConflictCase.identity.mergeTreeOid).toBeNull()
    expect(errorMergeConflictCase.identity.identityUnavailableReason).toMatch(/merge candidate was not constructed/)
    expect(errorMergeConflictCase.pipeline.find((stage) => stage.stage === 'merge')?.status).toBe('failed')
    expect(errorMergeConflictCase.pipeline.find((stage) => stage.stage === 'gate')?.status).toBe('not-started')
  })

  it('computes overview stats without putting Error in the pass-rate denominator', () => {
    const overview = buildOverview()
    const passed = MOCK_GATE_TREND.reduce((sum, point) => sum + point.passed, 0)
    const blocked = MOCK_GATE_TREND.reduce((sum, point) => sum + point.blocked, 0)
    const error = MOCK_GATE_TREND.reduce((sum, point) => sum + point.error, 0)
    expect(overview.stats.gatePassRate).toBe(passed / (passed + blocked))
    expect(overview.stats.errorRate).toBe(error / (passed + blocked + error))
    expect(overview.stats.unknownCostRecordCount).toBe(1)
    expect(overview.stats.knownCostUsd).toBeGreaterThan(0)
  })
})
