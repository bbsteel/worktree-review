import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AdminClientContext, type AdminClient } from '../app/admin-client.ts'
import type {
  ComputePolicyDto,
  ProviderProfileDto,
  RepositoryDto,
  RepositoryStatusDto,
  ReviewPolicyDto,
} from '../data/api/dto.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { NewReviewPage } from './NewReviewPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

const repository: RepositoryDto = {
  repository_id: 'repo_1',
  display_name: 'acme/payment-service',
  canonical_root: '/home/dev/projects/payment-service',
  last_gate_state: 'blocked',
  last_reviewed_at: '2026-09-08T10:00:00.000Z',
}

const cleanStatus: RepositoryStatusDto = {
  repository_id: 'repo_1',
  branch: 'main',
  head_oid: 'a3f8c1d92e4b70aa18c6d5e4f0b91c27d8e4a1b2',
  dirty: false,
  tracked_modifications: 0,
  untracked_files: 0,
  accessible: true,
  identity_drift: false,
}

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
  context_rules: [],
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

const providerProfile: ProviderProfileDto = {
  profile_id: 'pp_openai',
  name: 'openai-production',
  provider: 'openai',
  endpoint: null,
  local_cli_adapter: null,
  local_cli_command: null,
  adapter_label: null,
  credential_reference: '${OPENAI_API_KEY}',
  credential_state: 'configured',
  last_used_at: null,
  health: { profile_name: 'openai-production', status: 'healthy', observed_at: null },
  referenced_by_history: true,
  is_default: true,
}

interface FakeClientOptions {
  createReview?: AdminClient['createReview']
  status?: RepositoryStatusDto
  repositories?: RepositoryDto[]
}

function fakeClient(options: FakeClientOptions = {}): AdminClient {
  return {
    listRepositories: async () => options.repositories ?? [repository],
    getRepositoryStatus: async () => options.status ?? cleanStatus,
    listReviewPolicies: async () => [reviewPolicy],
    listComputePolicies: async () => [computePolicy],
    listProviderProfiles: async () => [providerProfile],
    createReview:
      options.createReview ??
      (async () => ({ attempt_id: 'attempt_01JNEW0001' })),
    // Unused by this page; typed stubs keep the AdminClient shape.
    retryReview: async () => ({ attempt_id: 'unused' }),
    getReviewResult: async () => ({}),
    getReviewRun: async () => {
      throw new Error('unused')
    },
    getOverview: async () => {
      throw new Error('unused')
    },
    listReviews: async () => ({ runs: [], nextCursor: null }),
    registerRepository: async () => repository,
    removeRepository: async () => undefined,
    createProviderProfile: async () => providerProfile,
    updateProviderProfile: async () => providerProfile,
    deleteProviderProfile: async () => undefined,
    testProviderProfile: async () => ({ ok: true, detail: 'ok', tested_at: '2026-09-09T16:00:00Z' }),
    getReviewPolicy: async () => reviewPolicy,
    getComputePolicy: async () => computePolicy,
    registerReviewPolicy: async () => reviewPolicy,
    registerComputePolicy: async () => computePolicy,
    getReviewPolicyDocument: async () => {
      throw new Error('unused')
    },
    saveReviewPolicyDocument: async () => {
      throw new Error('unused')
    },
    createManagedReviewPolicy: async () => reviewPolicy,
    unregisterReviewPolicy: async () => undefined,
    getComputePolicyDocument: async () => {
      throw new Error('unused')
    },
    saveComputePolicyDocument: async () => {
      throw new Error('unused')
    },
    createManagedComputePolicy: async () => computePolicy,
    unregisterComputePolicy: async () => undefined,
  }
}

function renderPage(client: AdminClient) {
  const router = createMemoryRouter(
    [
      {
        path: '/reviews/new',
        element: (
          <AdminClientContext.Provider value={client}>
            <NewReviewPage />
          </AdminClientContext.Provider>
        ),
      },
      { path: '/reviews/:attemptId', element: <p>detail route</p> },
      { path: '/repositories', element: <p>repositories route</p> },
    ],
    { initialEntries: ['/reviews/new'] },
  )
  render(<RouterProvider router={router} />)
  return router
}

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(
    await screen.findByRole('combobox', { name: 'Authorized repository' }),
    'repo_1',
  )
  await user.selectOptions(
    screen.getByRole('combobox', { name: /Trusted Review Policy/ }),
    'rp_default',
  )
  await user.selectOptions(
    screen.getByRole('combobox', { name: /Trusted Compute Policy/ }),
    'cp_gpt',
  )
}

describe('NewReviewPage', () => {
  it('hard-blocks submit when the local setup catalog is incomplete', async () => {
    renderPage(
      fakeClient({
        repositories: [],
      }),
    )

    expect(
      await screen.findByRole('region', { name: 'Finish local setup before starting a review' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start review' })).toBeDisabled()
  })

  it('shows repository, source, policy and disclosure sections before submit', async () => {
    renderPage(fakeClient())

    expect(await screen.findByText('acme/payment-service')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Repository' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Review Source' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Review Policy' })).toBeInTheDocument()
    expect(
      screen.getByRole('group', { name: 'Compute Policy & Provider Profile' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Confirm before starting')).toBeInTheDocument()
  })

  it('shows repository status and resolved provider disclosure', async () => {
    renderPage(fakeClient())
    const user = userEvent.setup()
    await fillRequiredFields(user)

    expect(await screen.findByText('main')).toBeInTheDocument()
    expect(screen.getByText('Clean')).toBeInTheDocument()
    expect(screen.getByText('openai-production')).toBeInTheDocument()
    expect(screen.getByText('${OPENAI_API_KEY}', { exact: false })).toBeInTheDocument()
    expect(screen.getAllByText(/OpenAI API \(United States\)/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Provider-stated 30 days/)).toBeInTheDocument()
  })

  it('validates required fields inline without submitting', async () => {
    const createReview = vi.fn<AdminClient['createReview']>()
    renderPage(fakeClient({ createReview }))
    await screen.findByText('acme/payment-service')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Start review' }))

    expect(screen.getByText('Select an authorized repository.')).toBeInTheDocument()
    expect(createReview).not.toHaveBeenCalled()
  })

  it('applies source-mode field rules', async () => {
    renderPage(fakeClient())
    await screen.findByText('acme/payment-service')
    const user = userEvent.setup()

    await user.click(screen.getByRole('radio', { name: 'Recent commits + worktree' }))
    expect(screen.getByRole('spinbutton', { name: /Commit count/ })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Proposed' })).toBeDisabled()

    await user.click(screen.getByRole('radio', { name: 'Committed ref' }))
    const proposed = screen.getByRole('textbox', { name: 'Proposed' })
    expect(proposed).toBeEnabled()
    expect(screen.getByText(/worktree must be clean/i)).toBeInTheDocument()
  })

  it('blocks committed-ref submission when the worktree is dirty', async () => {
    const createReview = vi.fn<AdminClient['createReview']>()
    renderPage(fakeClient({ createReview, status: { ...cleanStatus, dirty: true, tracked_modifications: 2 } }))
    const user = userEvent.setup()
    await fillRequiredFields(user)
    await screen.findByText(/Modified — 2 tracked/)
    await user.click(screen.getByRole('radio', { name: 'Committed ref' }))
    await user.type(screen.getByRole('textbox', { name: 'Proposed' }), 'feature/x')

    await user.click(screen.getByRole('button', { name: 'Start review' }))

    expect(screen.getByText(/require a clean worktree/)).toBeInTheDocument()
    expect(createReview).not.toHaveBeenCalled()
  })

  it('submits with an idempotency key and navigates to the new attempt', async () => {
    const createReview = vi.fn<AdminClient['createReview']>(async () => ({
      attempt_id: 'attempt_01JNEW0001',
    }))
    const router = renderPage(fakeClient({ createReview }))
    const user = userEvent.setup()
    await fillRequiredFields(user)

    await user.click(screen.getByRole('button', { name: 'Start review' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/reviews/attempt_01JNEW0001')
    })
    expect(createReview).toHaveBeenCalledTimes(1)
    const [request, key] = createReview.mock.calls[0] ?? []
    expect(request).toEqual({
      repository_id: 'repo_1',
      source: { kind: 'local-worktree' },
      review_policy_id: 'rp_default',
      compute_policy_id: 'cp_gpt',
    })
    expect(key).toBeTruthy()
  })

  it('keeps the same idempotency key when retrying a failed submission', async () => {
    const keys: (string | undefined)[] = []
    let failures = 1
    const createReview = vi.fn<AdminClient['createReview']>(async (_request, key) => {
      keys.push(key)
      if (failures > 0) {
        failures -= 1
        throw new Error('connection reset')
      }
      return { attempt_id: 'attempt_01JNEW0002' }
    })
    const router = renderPage(fakeClient({ createReview }))
    const user = userEvent.setup()
    await fillRequiredFields(user)

    await user.click(screen.getByRole('button', { name: 'Start review' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be started/)

    await user.click(screen.getByRole('button', { name: 'Start review' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/reviews/attempt_01JNEW0002')
    })
    expect(keys).toHaveLength(2)
    expect(keys[0]).toBe(keys[1])
  })

  it('shows an honest error state when the service is unavailable', async () => {
    const client = fakeClient()
    client.listRepositories = async () => {
      throw new Error('network_unreachable: Failed to fetch')
    }
    renderPage(client)

    expect(
      await screen.findByText('New Review requires the live review service'),
    ).toBeInTheDocument()
    expect(screen.getByText(/mock mode does not create attempts/)).toBeInTheDocument()
  })

  it('guides to repository registration when none are authorized', async () => {
    renderPage(fakeClient({ repositories: [] }))

    expect(await screen.findByText('No authorized repositories')).toBeInTheDocument()
    expect(
      await screen.findByRole('region', { name: 'Finish local setup before starting a review' }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Open Repositories' }).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Start review' })).toBeDisabled()
  })
})
