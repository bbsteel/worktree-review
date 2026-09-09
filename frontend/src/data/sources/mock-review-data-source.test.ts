import { afterEach, describe, expect, it, vi } from 'vitest'
import { BLOCKED_DEMO_ATTEMPT_ID, MOCK_DATA_BADGE } from '../fixtures/index.ts'
import { createReviewDataSource } from './create-review-data-source.ts'
import { MockReviewDataSource } from './mock-review-data-source.ts'
import { ReviewNotFoundError } from './review-data-source.ts'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('MockReviewDataSource', () => {
  it('returns in-memory cases without writing mock runs to web storage', async () => {
    const localSet = vi.spyOn(Storage.prototype, 'setItem')
    const source = new MockReviewDataSource()

    const overview = await source.getOverview()
    const blocked = await source.getReviewRun(BLOCKED_DEMO_ATTEMPT_ID)
    const cases = await source.listCases()

    expect(source.kind).toBe('mock')
    expect(source.environmentBadge).toBe(MOCK_DATA_BADGE)
    expect(overview.attention[0]?.attemptId).toBe(BLOCKED_DEMO_ATTEMPT_ID)
    expect(blocked.gateState).toBe('blocked')
    expect(cases.filter((item) => item.provenance === 'handwritten-mock').map((item) => item.caseKey)).toEqual([
      'passed',
      'blocked',
      'error_merge_conflict',
    ])
    expect(cases.filter((item) => item.provenance === 'pipeline-snapshot')).toHaveLength(3)
    expect(localSet).not.toHaveBeenCalled()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('throws when the attempt does not exist', async () => {
    const source = new MockReviewDataSource()
    await expect(source.getReviewRun('attempt_missing')).rejects.toBeInstanceOf(ReviewNotFoundError)
  })
})

describe('createReviewDataSource', () => {
  it('creates the mock source by default', () => {
    const source = createReviewDataSource()
    expect(source).toBeInstanceOf(MockReviewDataSource)
    expect(source.kind).toBe('mock')
  })
})
