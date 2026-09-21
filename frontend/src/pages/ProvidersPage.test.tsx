import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AdminClientContext, type AdminClient } from '../app/admin-client.ts'
import type { ProviderProfileDto } from '../data/api/dto.ts'
import { createFakeAdminClient } from '../test/fake-admin-client.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { ProvidersPage } from './ProvidersPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

const remoteProfile: ProviderProfileDto = {
  profile_id: 'pp_openai',
  name: 'openai-production',
  provider: 'openai',
  endpoint: null,
  local_cli_adapter: null,
  local_cli_command: null,
  adapter_label: null,
  credential_reference: '${OPENAI_API_KEY}',
  credential_state: 'configured',
  last_used_at: '2026-09-08T10:00:00.000Z',
  health: { profile_name: 'openai-production', status: 'healthy', observed_at: '2026-09-09T14:12:00.000Z' },
  referenced_by_history: true,
  is_default: true,
}

const localProfile: ProviderProfileDto = {
  profile_id: 'pp_codex',
  name: 'codex-local',
  provider: 'local-cli',
  endpoint: null,
  local_cli_adapter: 'codex-cli',
  local_cli_command: ['codex', 'exec', '--json'],
  adapter_label: 'Codex CLI',
  credential_reference: null,
  credential_state: 'configured',
  last_used_at: null,
  health: { profile_name: 'codex-local', status: 'not_tested', observed_at: null },
  referenced_by_history: false,
  is_default: false,
}

function renderPage(client: AdminClient) {
  return render(
    <AdminClientContext.Provider value={client}>
      <ProvidersPage />
    </AdminClientContext.Provider>,
  )
}

function clientWithProfiles(): AdminClient {
  return createFakeAdminClient({
    listProviderProfiles: async () => [remoteProfile, localProfile],
  })
}

describe('ProvidersPage', () => {
  it('lists profiles with connectivity fields and credential state', async () => {
    renderPage(clientWithProfiles())

    expect(await screen.findByText('openai-production')).toBeInTheDocument()
    expect(screen.getByText('codex-local')).toBeInTheDocument()
    expect(screen.getAllByText('Credential: Configured')).toHaveLength(2)
    expect(screen.getByText('Default connection')).toBeInTheDocument()
    expect(screen.getByText(/Healthy at 2026-09-09 14:12:00 UTC/)).toBeInTheDocument()
    expect(screen.getByText('Not tested')).toBeInTheDocument()
    expect(screen.getByText('codex-cli (Codex CLI)')).toBeInTheDocument()
    expect(screen.getByText('codex exec --json')).toBeInTheDocument()
  })

  it('never displays a credential value, only the reference', async () => {
    renderPage(clientWithProfiles())
    await screen.findByText('openai-production')

    expect(screen.getByText('${OPENAI_API_KEY}')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('sk-')
  })

  it('keeps delete unavailable for profiles referenced by history', async () => {
    renderPage(clientWithProfiles())
    await screen.findByText('openai-production')

    const card = screen.getByText('openai-production').closest('li')
    expect(card).not.toBeNull()
    expect(
      within(card as HTMLElement).getByText(/Referenced by history/),
    ).toBeInTheDocument()
    expect(
      within(card as HTMLElement).queryByRole('button', { name: 'Delete' }),
    ).not.toBeInTheDocument()
  })

  it('creates a remote profile after validation, without calling the model', async () => {
    const createProviderProfile = vi.fn<AdminClient['createProviderProfile']>(
      async (requestBody) => ({
        ...remoteProfile,
        profile_id: 'pp_new',
        name: requestBody.name,
      }),
    )
    const testProviderProfile = vi.fn<AdminClient['testProviderProfile']>()
    renderPage(
      createFakeAdminClient({
        listProviderProfiles: async () => [],
        createProviderProfile,
        testProviderProfile,
      }),
    )
    const user = userEvent.setup()
    await screen.findByText('No provider profiles')

    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'anthropic-staging')
    const credentialField = screen.getByRole('textbox', { name: /Credential reference/ })
    await user.click(credentialField)
    await user.paste('${ANTHROPIC_API_KEY}')
    await user.click(screen.getByRole('button', { name: 'Create profile' }))

    expect(await screen.findByText('anthropic-staging')).toBeInTheDocument()
    expect(createProviderProfile).toHaveBeenCalledWith({
      name: 'anthropic-staging',
      provider: 'anthropic',
      endpoint: null,
      credential_reference: '${ANTHROPIC_API_KEY}',
      local_cli_adapter: null,
      local_cli_command: null,
      adapter_label: null,
    })
    expect(testProviderProfile).not.toHaveBeenCalled()
  })

  it('rejects a raw secret pasted into the credential field', async () => {
    const createProviderProfile = vi.fn<AdminClient['createProviderProfile']>()
    renderPage(createFakeAdminClient({ createProviderProfile }))
    const user = userEvent.setup()
    await screen.findByText('No provider profiles')

    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'bad-profile')
    await user.type(screen.getByRole('textbox', { name: /Credential reference/ }), 'sk-livevalue')
    await user.click(screen.getByRole('button', { name: 'Create profile' }))

    expect(screen.getByText(/Use an environment variable reference like/)).toBeInTheDocument()
    expect(createProviderProfile).not.toHaveBeenCalled()
  })

  it('requires explicit confirmation before testing a connection', async () => {
    const testProviderProfile = vi.fn<AdminClient['testProviderProfile']>(async () => ({
      ok: true,
      detail: 'Authenticated; model list reachable.',
      tested_at: '2026-09-09T16:20:00.000Z',
    }))
    renderPage(
      createFakeAdminClient({
        listProviderProfiles: async () => [remoteProfile, localProfile],
        testProviderProfile,
      }),
    )
    const user = userEvent.setup()

    await screen.findByText('openai-production')
    const card = screen.getByText('openai-production').closest('li') as HTMLElement
    await user.click(within(card).getByRole('button', { name: 'Test connection' }))

    expect(testProviderProfile).not.toHaveBeenCalled()
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/no API call is made/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Run test' }))

    expect(testProviderProfile).toHaveBeenCalledWith('pp_openai')
    expect(
      await within(card).findByText(/Test succeeded at 2026-09-09 16:20:00 UTC/),
    ).toBeInTheDocument()
  })

  it('shows a failed connection test as an error state', async () => {
    renderPage(
      createFakeAdminClient({
        listProviderProfiles: async () => [remoteProfile],
        testProviderProfile: async () => ({
          ok: false,
          detail: 'credential_missing: OPENAI_API_KEY is not set',
          tested_at: '2026-09-09T16:25:00.000Z',
        }),
      }),
    )
    const user = userEvent.setup()
    await screen.findByText('openai-production')

    await user.click(screen.getByRole('button', { name: 'Test connection' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Run test' }))

    expect(await screen.findByText(/Test failed/)).toHaveTextContent(/credential_missing/)
  })
})
