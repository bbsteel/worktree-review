import type { FixtureCaseDescriptor, OverviewView } from '../../domain/overview.ts'
import type {
  AuditEventFilter,
  AuditEventPageView,
  AuthSessionView,
  BypassSubmissionView,
} from '../../domain/audit.ts'
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
  /**
   * P3 authorized-deployment surface. Mock/demo sources leave these
   * unimplemented: the demo build must never submit a real bypass or fabricate
   * audit data.
   */
  getAuthSession?(): Promise<AuthSessionView>
  listAuditEvents?(
    filter: AuditEventFilter,
    cursor: string | null,
    limit?: number,
  ): Promise<AuditEventPageView>
  bypassFinding?(
    attemptId: string,
    fingerprint: string,
    reason: string,
  ): Promise<BypassSubmissionView>
  logout?(): Promise<void>
}

export class ReviewNotFoundError extends Error {
  readonly attemptId: string

  constructor(attemptId: string) {
    super(`Review attempt not found: ${attemptId}`)
    this.name = 'ReviewNotFoundError'
    this.attemptId = attemptId
  }
}
