import { describe, expect, it } from 'vitest'
import {
  buildSaveProfileRequest,
  INITIAL_PROFILE_FORM,
  parseArgv,
  validateProfileForm,
  type ProviderProfileFormState,
} from './provider-profile-form.ts'

function remoteForm(overrides: Partial<ProviderProfileFormState> = {}): ProviderProfileFormState {
  return {
    ...INITIAL_PROFILE_FORM,
    name: 'openai-production',
    provider: 'openai',
    credentialReference: '${OPENAI_API_KEY}',
    ...overrides,
  }
}

describe('validateProfileForm', () => {
  it('requires a name', () => {
    expect(validateProfileForm(remoteForm({ name: ' ' })).name).toBeTruthy()
  })

  it('accepts a valid remote profile', () => {
    expect(validateProfileForm(remoteForm())).toEqual({})
  })

  it('rejects non-HTTPS endpoints', () => {
    expect(
      validateProfileForm(remoteForm({ endpoint: 'http://insecure.example.com' })).endpoint,
    ).toBeTruthy()
    expect(
      validateProfileForm(remoteForm({ endpoint: 'https://api.openai.com' })).endpoint,
    ).toBeUndefined()
  })

  it('validates credential references as env var names', () => {
    expect(
      validateProfileForm(remoteForm({ credentialReference: 'sk-live-key-value' }))
        .credentialReference,
    ).toBeTruthy()
    expect(
      validateProfileForm(remoteForm({ credentialReference: '${ANTHROPIC_API_KEY}' }))
        .credentialReference,
    ).toBeUndefined()
  })

  it('requires adapter and argv for local-cli profiles', () => {
    const errors = validateProfileForm({
      ...INITIAL_PROFILE_FORM,
      profileKind: 'local-cli',
      name: 'codex-local',
    })
    expect(errors.localCliAdapter).toBeTruthy()
    expect(errors.localCliCommandText).toBeTruthy()
  })
})

describe('parseArgv', () => {
  it('splits one argument per line and drops blanks', () => {
    expect(parseArgv('codex\n\nexec\n  --json  ')).toEqual(['codex', 'exec', '--json'])
  })
})

describe('buildSaveProfileRequest', () => {
  it('builds a remote request without local-cli fields', () => {
    expect(buildSaveProfileRequest(remoteForm({ endpoint: '' }))).toEqual({
      name: 'openai-production',
      provider: 'openai',
      endpoint: null,
      credential_reference: '${OPENAI_API_KEY}',
      local_cli_adapter: null,
      local_cli_command: null,
      adapter_label: null,
    })
  })

  it('builds a local-cli request with argv and no credential value', () => {
    const request = buildSaveProfileRequest({
      ...INITIAL_PROFILE_FORM,
      profileKind: 'local-cli',
      name: 'codex-local',
      localCliAdapter: 'codex-cli',
      localCliCommandText: 'codex\nexec',
      adapterLabel: 'Codex CLI',
    })
    expect(request).toEqual({
      name: 'codex-local',
      provider: 'local-cli',
      endpoint: null,
      credential_reference: null,
      local_cli_adapter: 'codex-cli',
      local_cli_command: ['codex', 'exec'],
      adapter_label: 'Codex CLI',
    })
  })
})
