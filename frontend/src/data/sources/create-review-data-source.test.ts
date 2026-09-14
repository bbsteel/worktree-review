import { afterEach, describe, expect, it, vi } from 'vitest'
import { createReviewDataSource } from './create-review-data-source.ts'

describe('createReviewDataSource', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('defaults to the live data source when no mode is configured', () => {
    vi.stubEnv('VITE_REVIEW_DATA_SOURCE', '')
    const source = createReviewDataSource()
    expect(source.kind).toBe('live')
    expect(source.environmentBadge).toBeNull()
  })

  it('uses the live data source for an explicit live build', () => {
    vi.stubEnv('VITE_REVIEW_DATA_SOURCE', 'live')
    expect(createReviewDataSource().kind).toBe('live')
  })

  it('only enables the offline demo through the explicit mock mode', () => {
    vi.stubEnv('VITE_REVIEW_DATA_SOURCE', 'mock')
    const source = createReviewDataSource()
    expect(source.kind).toBe('mock')
    expect(source.environmentBadge).not.toBeNull()
  })

  it('rejects unknown modes instead of silently falling back to mock', () => {
    vi.stubEnv('VITE_REVIEW_DATA_SOURCE', 'staging')
    expect(() => createReviewDataSource()).toThrow(/Unknown VITE_REVIEW_DATA_SOURCE/)
  })
})
