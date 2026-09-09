import { MockReviewDataSource } from './mock-review-data-source.ts'
import type { ReviewDataSource } from './review-data-source.ts'

export function createReviewDataSource(): ReviewDataSource {
  const mode = import.meta.env.VITE_REVIEW_DATA_SOURCE ?? 'mock'
  if (mode === 'live') {
    throw new Error('Live ReviewDataSource is not implemented in this prototype.')
  }
  if (mode !== 'mock') {
    throw new Error(`Unknown VITE_REVIEW_DATA_SOURCE: ${mode}`)
  }
  return new MockReviewDataSource()
}
