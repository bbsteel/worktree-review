import type { FixtureCaseDescriptor, OverviewView } from '../../domain/overview.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import type { FixtureCaseKey } from '../fixtures/index.ts'

export type ReviewDataSourceKind = 'mock' | 'live'

export interface ReviewDataSource {
  readonly kind: ReviewDataSourceKind
  /** Shown globally for mock/pre-alpha. Live sources return null. */
  readonly environmentBadge: string | null
  getOverview(): Promise<OverviewView>
  getReviewRun(attemptId: string): Promise<ReviewRunView>
  listCases(): Promise<FixtureCaseDescriptor[]>
  getCase(caseKey: FixtureCaseKey): Promise<ReviewRunView>
}

export class ReviewNotFoundError extends Error {
  readonly attemptId: string

  constructor(attemptId: string) {
    super(`Review attempt not found: ${attemptId}`)
    this.name = 'ReviewNotFoundError'
    this.attemptId = attemptId
  }
}
