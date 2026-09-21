/**
 * Pure form model for Provider Connection Profiles (design 12).
 * Profiles describe connectivity only: provider, endpoint or local-cli
 * adapter, and a credential *reference*. Model, budget, pricing and
 * retention belong to Compute Policies and must not be edited here.
 */
import type { SaveProviderProfileRequestDto } from '../../data/api/dto.ts'

export type ProfileKind = 'remote' | 'local-cli'

export interface ProviderProfileFormState {
  profileKind: ProfileKind
  name: string
  provider: string
  endpoint: string
  credentialReference: string
  localCliAdapter: string
  /** One argv element per line; executed without a shell. */
  localCliCommandText: string
  adapterLabel: string
}

export const INITIAL_PROFILE_FORM: ProviderProfileFormState = {
  profileKind: 'remote',
  name: '',
  provider: 'anthropic',
  endpoint: '',
  credentialReference: '',
  localCliAdapter: '',
  localCliCommandText: '',
  adapterLabel: '',
}

export const CREDENTIAL_REFERENCE_PATTERN = /^\$\{[A-Za-z_][A-Za-z0-9_]*\}$/

export type ProviderProfileFormErrors = Partial<
  Record<'name' | 'endpoint' | 'credentialReference' | 'localCliAdapter' | 'localCliCommandText', string>
>

export function parseArgv(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

export function validateProfileForm(
  state: ProviderProfileFormState,
): ProviderProfileFormErrors {
  const errors: ProviderProfileFormErrors = {}

  if (state.name.trim() === '') {
    errors.name = 'A profile name is required.'
  }

  if (state.profileKind === 'remote') {
    if (state.endpoint.trim() !== '' && !/^https:\/\//.test(state.endpoint.trim())) {
      errors.endpoint = 'Endpoints must use https:// — credentials must never travel over plain HTTP.'
    }
    if (
      state.credentialReference.trim() !== '' &&
      !CREDENTIAL_REFERENCE_PATTERN.test(state.credentialReference.trim())
    ) {
      errors.credentialReference = 'Use an environment variable reference like ${OPENAI_API_KEY}.'
    }
  } else {
    if (state.localCliAdapter.trim() === '') {
      errors.localCliAdapter = 'A local-cli adapter is required.'
    }
    if (parseArgv(state.localCliCommandText).length === 0) {
      errors.localCliCommandText = 'A command argv is required. It runs without a shell.'
    }
  }

  return errors
}

export function buildSaveProfileRequest(
  state: ProviderProfileFormState,
): SaveProviderProfileRequestDto {
  if (state.profileKind === 'remote') {
    return {
      name: state.name.trim(),
      provider: state.provider,
      endpoint: state.endpoint.trim() === '' ? null : state.endpoint.trim(),
      credential_reference:
        state.credentialReference.trim() === '' ? null : state.credentialReference.trim(),
      local_cli_adapter: null,
      local_cli_command: null,
      adapter_label: null,
    }
  }
  return {
    name: state.name.trim(),
    provider: 'local-cli',
    endpoint: null,
    credential_reference: null,
    local_cli_adapter: state.localCliAdapter.trim(),
    local_cli_command: parseArgv(state.localCliCommandText),
    adapter_label: state.adapterLabel.trim() === '' ? null : state.adapterLabel.trim(),
  }
}
