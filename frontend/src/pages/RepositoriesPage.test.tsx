import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AdminClientContext, type AdminClient } from '../app/admin-client.ts'
import type { RepositoryDto, RepositoryStatusDto } from '../data/api/dto.ts'
import { ApiError } from '../data/api/review-api-client.ts'
import { createFakeAdminClient } from '../test/fake-admin-client.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { RepositoriesPage } from './RepositoriesPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
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

const status: RepositoryStatusDto = {
  repository_id: 'repo_1',
  branch: 'main',
  head_oid: 'a3f8c1d92e4b70aa18c6d5e4f0b91c27d8e4a1b2',
  dirty: true,
  tracked_modifications: 3,
  untracked_files: 1,
  accessible: true,
  identity_drift: false,
}

function renderPage(client: AdminClient) {
  return render(
    <AdminClientContext.Provider value={client}>
      <RepositoriesPage />
    </AdminClientContext.Provider>,
  )
}

function clientWithRepositories(): AdminClient {
  return createFakeAdminClient({
    listRepositories: async () => [repository],
    getRepositoryStatus: async () => status,
  })
}

describe('RepositoriesPage', () => {
  it('lists authorized repositories with identity, status and last gate', async () => {
    renderPage(clientWithRepositories())

    expect(await screen.findByText('acme/payment-service')).toBeInTheDocument()
    expect(screen.getByText('/home/dev/projects/payment-service')).toBeInTheDocument()
    expect(screen.getByText('Last gate: Blocked')).toBeInTheDocument()
    expect(screen.getByText('Worktree modified')).toBeInTheDocument()
    expect(screen.getByText('main')).toBeInTheDocument()
    expect(screen.getByText('3 tracked · 1 untracked')).toBeInTheDocument()
    expect(screen.getByText('2026-09-08 10:00:00 UTC')).toBeInTheDocument()
  })

  it('warns on identity drift and inaccessible roots', async () => {
    renderPage(
      createFakeAdminClient({
        listRepositories: async () => [repository],
        getRepositoryStatus: async () => ({ ...status, accessible: false, identity_drift: true }),
      }),
    )

    expect(await screen.findByText('Not accessible')).toBeInTheDocument()
    expect(screen.getByText('Identity drift detected')).toBeInTheDocument()
  })

  it('registers a repository and shows its status', async () => {
    const registerRepository = vi.fn<AdminClient['registerRepository']>(async () => ({
      ...repository,
      repository_id: 'repo_2',
      display_name: 'acme/new-service',
    }))
    renderPage(
      createFakeAdminClient({
        registerRepository,
        getRepositoryStatus: async () => ({ ...status, repository_id: 'repo_2', dirty: false }),
      }),
    )
    const user = userEvent.setup()

    await screen.findByRole('heading', { name: 'Repositories' })
    await user.type(
      screen.getByRole('textbox', { name: 'Repository path' }),
      '/home/dev/projects/new-service',
    )
    await user.type(screen.getByRole('textbox', { name: /Display name/ }), 'acme/new-service')
    await user.click(screen.getByRole('button', { name: 'Register repository' }))

    expect(await screen.findByText('acme/new-service')).toBeInTheDocument()
    expect(registerRepository).toHaveBeenCalledWith({
      path: '/home/dev/projects/new-service',
      display_name: 'acme/new-service',
    })
  })

  it('requires a path and shows inline errors', async () => {
    const registerRepository = vi.fn<AdminClient['registerRepository']>()
    renderPage(createFakeAdminClient({ registerRepository }))
    const user = userEvent.setup()

    await screen.findByRole('heading', { name: 'Repositories' })
    await user.click(screen.getByRole('button', { name: 'Register repository' }))
    expect(screen.getByRole('alert')).toHaveTextContent('A repository path is required.')
    expect(registerRepository).not.toHaveBeenCalled()
  })

  it('shows registration failures without changing the list', async () => {
    renderPage(
      createFakeAdminClient({
        registerRepository: async () => {
          throw new ApiError('path_not_a_repository', 'No git repository at this path.', 422)
        },
      }),
    )
    const user = userEvent.setup()

    await screen.findByRole('heading', { name: 'Repositories' })
    await user.type(screen.getByRole('textbox', { name: 'Repository path' }), '/tmp/nope')
    await user.click(screen.getByRole('button', { name: 'Register repository' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('path_not_a_repository')
    expect(screen.getByText('No authorized repositories')).toBeInTheDocument()
  })

  it('confirms removal with copy that nothing on disk is deleted', async () => {
    const removeRepository = vi.fn<AdminClient['removeRepository']>(async () => undefined)
    renderPage(
      createFakeAdminClient({
        listRepositories: async () => [repository],
        getRepositoryStatus: async () => status,
        removeRepository,
      }),
    )
    const user = userEvent.setup()

    await screen.findByText('acme/payment-service')
    await user.click(screen.getByRole('button', { name: 'Remove authorization' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/does not delete the repository on disk/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Remove authorization' }))

    await waitFor(() => {
      expect(screen.queryByText('acme/payment-service')).not.toBeInTheDocument()
    })
    expect(removeRepository).toHaveBeenCalledWith('repo_1')
    expect(screen.getByText('No authorized repositories')).toBeInTheDocument()
  })

  it('cancelling removal keeps the repository', async () => {
    const removeRepository = vi.fn<AdminClient['removeRepository']>()
    renderPage(clientWithRepositories())
    const user = userEvent.setup()

    await screen.findByText('acme/payment-service')
    await user.click(screen.getByRole('button', { name: 'Remove authorization' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(removeRepository).not.toHaveBeenCalled()
    expect(screen.getByText('acme/payment-service')).toBeInTheDocument()
  })

  it('shows an honest error when the service is unavailable', async () => {
    renderPage(
      createFakeAdminClient({
        listRepositories: async () => {
          throw new Error('network_unreachable')
        },
      }),
    )

    expect(
      await screen.findByText('Repositories require the live review service'),
    ).toBeInTheDocument()
  })
})
