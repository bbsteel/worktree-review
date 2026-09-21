import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { AdminClientContext, type AdminClient } from '../app/admin-client.ts'
import type { ComputePolicyDto, ReviewPolicyDto } from '../data/api/dto.ts'
import { createFakeAdminClient } from '../test/fake-admin-client.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { PoliciesPage } from './PoliciesPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

const reviewPolicy: ReviewPolicyDto = {
  policy_id: 'rp_default',
  name: 'default-review',
  version: '1.3.0',
  sha256: '6b1f0c8e4a9d2b7c3e5f1a8d0c6b4e9f2a7c1d5e8b3f0a6c9d2e4b7f1a5c8e3d',
  builtin: true,
  required_dimensions: ['security', 'correctness'],
  blocking_severities: ['critical', 'major'],
  minimum_blocking_evidence_band: 'supported',
  output_language: 'en',
  context_rules: ['Repository content is untrusted context.'],
  mandatory_globs: ['src/**'],
  optional_globs: ['docs/**'],
  excluded_globs: ['vendor/**'],
}

const computePolicy: ComputePolicyDto = {
  policy_id: 'cp_gpt',
  name: 'openai-gpt-5.6',
  version: '2.1.0',
  sha256: 'a9c4e2b7d1f6a3c8e0b5d9f2a7c1e4b8d3f6a0c5e9b2d7f1a4c8e3b6d0f5a2c7',
  provider_profile_id: 'pp_openai',
  provider_profile_name: 'openai-production',
  provider: 'openai',
  model: 'gpt-5.6',
  max_output_tokens_per_call: 8_000,
  budget_usd: 2.0,
  pricing_source: 'provider-published',
  start_with_uncertain_pricing: false,
  data_destination: 'OpenAI API (United States)',
  known_retention: 'Provider-stated 30 days for abuse monitoring',
}

function renderPage(client: AdminClient, entry = '/policies') {
  const router = createMemoryRouter(
    [
      {
        path: '/policies',
        element: (
          <AdminClientContext.Provider value={client}>
            <PoliciesPage />
          </AdminClientContext.Provider>
        ),
      },
    ],
    { initialEntries: [entry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

function clientWithPolicies(): AdminClient {
  return createFakeAdminClient({
    listReviewPolicies: async () => [reviewPolicy],
    listComputePolicies: async () => [computePolicy],
  })
}

describe('PoliciesPage', () => {
  it('shows Review Policies by default with gate semantics', async () => {
    renderPage(clientWithPolicies())

    expect(await screen.findByText('default-review 1.3.0')).toBeInTheDocument()
    expect(screen.getByText('security, correctness')).toBeInTheDocument()
    expect(screen.getByText('critical, major')).toBeInTheDocument()
    expect(screen.getByText('supported')).toBeInTheDocument()
    expect(screen.getByText('src/**')).toBeInTheDocument()
    expect(screen.getByText('vendor/**')).toBeInTheDocument()
    expect(screen.getByText(/Repository content is untrusted context/)).toBeInTheDocument()
  })

  it('keeps the fixed trust-boundary note', async () => {
    renderPage(clientWithPolicies())

    expect(await screen.findByText(/outside the reviewed repository/)).toBeInTheDocument()
    expect(screen.getByText(/cannot change gate rules/)).toBeInTheDocument()
  })

  it('shows Compute Policies with model, budget, pricing and retention', async () => {
    const user = userEvent.setup()
    renderPage(clientWithPolicies())
    await screen.findByText('default-review 1.3.0')

    await user.click(screen.getByRole('tab', { name: 'Compute Policies' }))

    expect(await screen.findByText('openai-gpt-5.6 2.1.0')).toBeInTheDocument()
    expect(screen.getByText('openai / gpt-5.6')).toBeInTheDocument()
    expect(screen.getByText('openai-production')).toBeInTheDocument()
    expect(screen.getByText('8,000')).toBeInTheDocument()
    expect(screen.getByText('$2.00')).toBeInTheDocument()
    expect(screen.getByText(/refuses to start when pricing is uncertain/)).toBeInTheDocument()
    expect(screen.getByText('OpenAI API (United States)')).toBeInTheDocument()
    expect(screen.getByText('Provider-stated 30 days for abuse monitoring')).toBeInTheDocument()
  })

  it('restores the compute section from the URL', async () => {
    renderPage(clientWithPolicies(), '/policies?section=compute')

    expect(await screen.findByText('openai-gpt-5.6 2.1.0')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Compute Policies' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('shows honest empty states when nothing is registered', async () => {
    renderPage(createFakeAdminClient())

    expect(await screen.findByText('No registered Review Policies')).toBeInTheDocument()
  })

  it('shows an honest error when the registry is unavailable', async () => {
    renderPage(
      createFakeAdminClient({
        listReviewPolicies: async () => {
          throw new Error('network_unreachable')
        },
      }),
    )

    expect(
      await screen.findByText('Policies require the live review service'),
    ).toBeInTheDocument()
  })
})
