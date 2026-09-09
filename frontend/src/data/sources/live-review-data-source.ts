import type { FixtureCaseDescriptor, OverviewView } from '../../domain/overview.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import { ReviewApiClient, type ReviewApiClientConfig } from '../api/review-api-client.ts'
import type { FixtureCaseKey } from '../fixtures/index.ts'
import { getPipelineSnapshot, listPipelineSnapshots } from '../snapshots/index.ts'
import { ReviewNotFoundError, type ReviewDataSource } from './review-data-source.ts'

/**
 * Live data source over /api/v1 (design 16). Case snapshots remain the
 * immutable, real-pipeline JSON bundled with the app — they are local static
 * assets and must also open without a server connection (design 15).
 */
export class LiveReviewDataSource implements ReviewDataSource {
  readonly kind = 'live' as const
  readonly environmentBadge = null
  private readonly client: ReviewApiClient

  constructor(config: ReviewApiClientConfig = {}) {
    this.client = new ReviewApiClient(config)
  }

  async getOverview(): Promise<OverviewView> {
    return this.client.getOverview()
  }

  async getReviewRun(attemptId: string): Promise<ReviewRunView> {
    const snapshot = getPipelineSnapshot(attemptId)
    if (snapshot !== null) {
      return structuredClone(snapshot)
    }
    return this.client.getReviewRun(attemptId)
  }

  async listCases(): Promise<FixtureCaseDescriptor[]> {
    return listPipelineSnapshots()
  }

  async getCase(caseKey: FixtureCaseKey): Promise<ReviewRunView> {
    const snapshot = listPipelineSnapshots().find((entry) => entry.caseKey === caseKey)
    if (snapshot === undefined) {
      throw new ReviewNotFoundError(`case:${caseKey}`)
    }
    return this.getReviewRun(snapshot.attemptId)
  }
}
