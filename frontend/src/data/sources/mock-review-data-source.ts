import type { FixtureCaseDescriptor, OverviewView } from '../../domain/overview.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import {
  getFixtureByAttemptId,
  getFixtureCase,
  listFixtureCases,
  MOCK_DATA_BADGE,
  type FixtureCaseKey,
} from '../fixtures/index.ts'
import { buildOverview } from '../fixtures/overview.ts'
import { getPipelineSnapshot, listPipelineSnapshots } from '../snapshots/index.ts'
import { ReviewNotFoundError, type ReviewDataSource } from './review-data-source.ts'

/**
 * In-memory prototype data. It never writes mock runs into browser storage or a
 * run-history database. Production live history is a later store.
 */
export class MockReviewDataSource implements ReviewDataSource {
  readonly kind = 'mock' as const
  readonly environmentBadge = MOCK_DATA_BADGE

  async getOverview(): Promise<OverviewView> {
    return structuredClone(buildOverview())
  }

  async getReviewRun(attemptId: string): Promise<ReviewRunView> {
    const run = getFixtureByAttemptId(attemptId) ?? getPipelineSnapshot(attemptId)
    if (!run) {
      throw new ReviewNotFoundError(attemptId)
    }
    return structuredClone(run)
  }

  async listCases(): Promise<FixtureCaseDescriptor[]> {
    return [...listFixtureCases(), ...listPipelineSnapshots()]
  }

  async getCase(caseKey: FixtureCaseKey): Promise<ReviewRunView> {
    return structuredClone(getFixtureCase(caseKey))
  }
}
