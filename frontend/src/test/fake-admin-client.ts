import type { AdminClient } from '../app/admin-client.ts'

/**
 * In-memory AdminClient stub for page tests. Every method resolves with an
 * empty/default payload; override per test with vi.fn() to capture calls.
 */
export function createFakeAdminClient(overrides: Partial<AdminClient> = {}): AdminClient {
  return {
    createReview: async () => ({ attempt_id: 'attempt_fake' }),
    retryReview: async () => ({ attempt_id: 'attempt_fake_retry' }),
    getReviewResult: async () => ({}),
    getReviewRun: async () => {
      throw new Error('not stubbed')
    },
    getOverview: async () => {
      throw new Error('not stubbed')
    },
    listReviews: async () => ({ runs: [], nextCursor: null }),
    listRepositories: async () => [],
    registerRepository: async () => {
      throw new Error('not stubbed')
    },
    getRepositoryStatus: async () => {
      throw new Error('not stubbed')
    },
    removeRepository: async () => undefined,
    listProviderProfiles: async () => [],
    createProviderProfile: async () => {
      throw new Error('not stubbed')
    },
    updateProviderProfile: async () => {
      throw new Error('not stubbed')
    },
    deleteProviderProfile: async () => undefined,
    testProviderProfile: async () => ({ ok: true, detail: 'ok', tested_at: '2026-09-09T16:00:00Z' }),
    listReviewPolicies: async () => [],
    getReviewPolicy: async () => {
      throw new Error('not stubbed')
    },
    listComputePolicies: async () => [],
    getComputePolicy: async () => {
      throw new Error('not stubbed')
    },
    registerReviewPolicy: async () => {
      throw new Error('not stubbed')
    },
    registerComputePolicy: async () => {
      throw new Error('not stubbed')
    },
    getReviewPolicyDocument: async () => {
      throw new Error('not stubbed')
    },
    saveReviewPolicyDocument: async () => {
      throw new Error('not stubbed')
    },
    createManagedReviewPolicy: async () => {
      throw new Error('not stubbed')
    },
    unregisterReviewPolicy: async () => undefined,
    getComputePolicyDocument: async () => {
      throw new Error('not stubbed')
    },
    saveComputePolicyDocument: async () => {
      throw new Error('not stubbed')
    },
    createManagedComputePolicy: async () => {
      throw new Error('not stubbed')
    },
    unregisterComputePolicy: async () => undefined,
    ...overrides,
  }
}
