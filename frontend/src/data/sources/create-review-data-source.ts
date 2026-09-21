import { LiveReviewDataSource } from './live-review-data-source.ts'
import { MockReviewDataSource } from './mock-review-data-source.ts'
import type { ReviewDataSource } from './review-data-source.ts'

/**
 * Production builds are LIVE by default: the offline demo is only reachable
 * through the explicit `demo` Vite mode (`npm run build:demo`), which sets
 * VITE_REVIEW_DATA_SOURCE=mock. Anything else must be deliberate.
 */
export function createReviewDataSource(): ReviewDataSource {
  const mode = import.meta.env.VITE_REVIEW_DATA_SOURCE || 'live'
  if (mode === 'live') {
    return new LiveReviewDataSource()
  }
  if (mode !== 'mock') {
    throw new Error(`Unknown VITE_REVIEW_DATA_SOURCE: ${mode}`)
  }
  return new MockReviewDataSource()
}
