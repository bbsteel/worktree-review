/**
 * Local loopback setup readiness for Overview checklist and New Review
 * hard-block. Computed client-side from existing list/status DTOs.
 */
import type {
  ComputePolicyDto,
  ProviderProfileDto,
  RepositoryDto,
  ReviewPolicyDto,
} from '../../data/api/dto.ts'

export type ConfigSetupItemId = 'repository' | 'review-policy' | 'compute-policy'

export interface ConfigSetupItem {
  id: ConfigSetupItemId
  ready: boolean
  href: string
}

export interface ConfigSetupSnapshot {
  items: ConfigSetupItem[]
  allReady: boolean
  /** True when no repository or no usable review/compute closed loop exists. */
  catalogIncomplete: boolean
}

export function isComputePolicyReady(
  policy: ComputePolicyDto,
  providerProfiles: readonly ProviderProfileDto[],
): boolean {
  if (policy.provider_profile_id === '') {
    return false
  }
  const profile = providerProfiles.find(
    (item) => item.profile_id === policy.provider_profile_id,
  )
  // local-cli profiles report not_applicable (no secret env var); remote
  // providers need configured. missing / invalid_reference stay unready.
  return (
    profile !== undefined &&
    (profile.credential_state === 'configured' ||
      profile.credential_state === 'not_applicable')
  )
}

export function evaluateConfigSetup(input: {
  repositories: readonly RepositoryDto[]
  reviewPolicies: readonly ReviewPolicyDto[]
  computePolicies: readonly ComputePolicyDto[]
  providerProfiles: readonly ProviderProfileDto[]
}): ConfigSetupSnapshot {
  const hasRepository = input.repositories.length > 0
  const hasReviewPolicy = input.reviewPolicies.length > 0
  const hasReadyCompute = input.computePolicies.some((policy) =>
    isComputePolicyReady(policy, input.providerProfiles),
  )
  const items: ConfigSetupItem[] = [
    {
      id: 'repository',
      ready: hasRepository,
      href: '/repositories',
    },
    {
      id: 'review-policy',
      ready: hasReviewPolicy,
      href: '/policies',
    },
    {
      id: 'compute-policy',
      ready: hasReadyCompute,
      href: '/policies?section=compute',
    },
  ]
  return {
    items,
    allReady: items.every((item) => item.ready),
    catalogIncomplete: !hasRepository || !hasReviewPolicy || !hasReadyCompute,
  }
}

export function selectedComputeCredentialReady(
  computePolicy: ComputePolicyDto | null,
  providerProfiles: readonly ProviderProfileDto[],
): boolean {
  if (computePolicy === null) {
    return false
  }
  return isComputePolicyReady(computePolicy, providerProfiles)
}
