import { createContext, useContext } from 'react'
import { ReviewApiClient } from '../data/api/review-api-client.ts'

/**
 * Shared admin/API client surface for configuration pages (New Review,
 * Repositories, Providers, Policies). Declared as a structural interface so
 * tests inject in-memory fakes; production uses a same-origin live client.
 */
export type AdminClient = Pick<
  ReviewApiClient,
  | 'createReview'
  | 'retryReview'
  | 'getReviewResult'
  | 'getReviewRun'
  | 'getOverview'
  | 'listReviews'
  | 'listRepositories'
  | 'registerRepository'
  | 'getRepositoryStatus'
  | 'removeRepository'
  | 'listProviderProfiles'
  | 'createProviderProfile'
  | 'updateProviderProfile'
  | 'deleteProviderProfile'
  | 'testProviderProfile'
  | 'listReviewPolicies'
  | 'getReviewPolicy'
  | 'listComputePolicies'
  | 'getComputePolicy'
  | 'registerReviewPolicy'
  | 'registerComputePolicy'
  | 'getReviewPolicyDocument'
  | 'saveReviewPolicyDocument'
  | 'createManagedReviewPolicy'
  | 'unregisterReviewPolicy'
  | 'getComputePolicyDocument'
  | 'saveComputePolicyDocument'
  | 'createManagedComputePolicy'
  | 'unregisterComputePolicy'
>

export const AdminClientContext = createContext<AdminClient | null>(null)

let defaultClient: AdminClient | null = null

export function getDefaultAdminClient(): AdminClient {
  defaultClient ??= new ReviewApiClient()
  return defaultClient
}

export function useAdminClient(): AdminClient {
  return useContext(AdminClientContext) ?? getDefaultAdminClient()
}
