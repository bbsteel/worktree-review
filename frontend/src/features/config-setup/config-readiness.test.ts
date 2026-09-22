import { describe, expect, it } from 'vitest'
import type {
  ComputePolicyDto,
  ProviderProfileDto,
  RepositoryDto,
  ReviewPolicyDto,
} from '../../data/api/dto.ts'
import {
  evaluateConfigSetup,
  isComputePolicyReady,
  selectedComputeCredentialReady,
} from './config-readiness.ts'

const repository: RepositoryDto = {
  repository_id: 'repo-1',
  display_name: 'demo',
  canonical_root: '/home/dev/demo',
  last_gate_state: null,
  last_reviewed_at: null,
}

const reviewPolicy: ReviewPolicyDto = {
  policy_id: 'builtin-review-policy',
  name: 'Built-in',
  version: '0.1.0',
  sha256: 'abc',
  builtin: true,
  required_dimensions: ['correctness'],
  blocking_severities: ['critical'],
  minimum_blocking_evidence_band: 'supported',
  output_language: 'en',
  context_rules: [],
  mandatory_globs: [],
  optional_globs: [],
  excluded_globs: [],
}

const computePolicy: ComputePolicyDto = {
  policy_id: 'compute-1',
  name: 'compute',
  version: '0.1.0',
  sha256: 'def',
  provider_profile_id: 'profile-1',
  provider_profile_name: 'anthropic',
  provider: 'anthropic',
  model: 'claude',
  max_output_tokens_per_call: 1024,
  budget_usd: null,
  pricing_source: 'manual',
  start_with_uncertain_pricing: true,
  data_destination: 'https://api.anthropic.com',
  known_retention: 'unknown',
}

const configuredProfile: ProviderProfileDto = {
  profile_id: 'profile-1',
  name: 'anthropic',
  provider: 'anthropic',
  endpoint: 'https://api.anthropic.com',
  credential_reference: '${ANTHROPIC_API_KEY}',
  credential_state: 'configured',
  local_cli_adapter: null,
  local_cli_command: null,
  adapter_label: null,
  last_used_at: null,
  health: { profile_name: 'anthropic', status: 'not_tested', observed_at: null },
  referenced_by_history: false,
  is_default: false,
}

describe('config-readiness', () => {
  it('marks compute ready when bound profile credential is configured or not_applicable', () => {
    expect(isComputePolicyReady(computePolicy, [configuredProfile])).toBe(true)
    expect(
      isComputePolicyReady(computePolicy, [
        { ...configuredProfile, credential_state: 'not_applicable' },
      ]),
    ).toBe(true)
    expect(
      isComputePolicyReady(computePolicy, [
        { ...configuredProfile, credential_state: 'missing' },
      ]),
    ).toBe(false)
    expect(
      isComputePolicyReady({ ...computePolicy, provider_profile_id: '' }, [configuredProfile]),
    ).toBe(false)
  })

  it('evaluates the three checklist rows without a separate provider row', () => {
    const incomplete = evaluateConfigSetup({
      repositories: [],
      reviewPolicies: [],
      computePolicies: [],
      providerProfiles: [],
    })
    expect(incomplete.allReady).toBe(false)
    expect(incomplete.catalogIncomplete).toBe(true)
    expect(incomplete.items.map((item) => item.id)).toEqual([
      'repository',
      'review-policy',
      'compute-policy',
    ])

    const ready = evaluateConfigSetup({
      repositories: [repository],
      reviewPolicies: [reviewPolicy],
      computePolicies: [computePolicy],
      providerProfiles: [configuredProfile],
    })
    expect(ready.allReady).toBe(true)
    expect(ready.catalogIncomplete).toBe(false)
  })

  it('treats builtin review policy as sufficient for the review-policy row', () => {
    const snapshot = evaluateConfigSetup({
      repositories: [repository],
      reviewPolicies: [reviewPolicy],
      computePolicies: [computePolicy],
      providerProfiles: [configuredProfile],
    })
    expect(snapshot.items.find((item) => item.id === 'review-policy')?.ready).toBe(true)
  })

  it('reports selected compute credential readiness for field-level block', () => {
    expect(selectedComputeCredentialReady(computePolicy, [configuredProfile])).toBe(true)
    expect(selectedComputeCredentialReady(null, [configuredProfile])).toBe(false)
  })
})
