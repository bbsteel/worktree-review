/**
 * Dual-mode Policy draft helpers: form subset fields patch a parsed YAML map
 * while preserving unknown keys for advanced YAML editing.
 *
 * Policy schemas use ``additionalProperties: false`` and have no ``name``
 * field — display names come from the registered path basename.
 */
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'

export type PolicyKind = 'review' | 'compute'

export interface ReviewPolicyFormFields {
  version: string
  blockingSeverities: string
}

export interface ComputePolicyFormFields {
  version: string
  provider: string
  model: string
}

export function parsePolicyDocument(text: string): Record<string, unknown> {
  const loaded = parseYaml(text)
  if (loaded === null || typeof loaded !== 'object' || Array.isArray(loaded)) {
    throw new Error('Policy document must be a YAML mapping')
  }
  return loaded as Record<string, unknown>
}

export function reviewFormFromDocument(document: Record<string, unknown>): ReviewPolicyFormFields {
  const blocking = document.blocking_severities
  return {
    version: typeof document.version === 'string' ? document.version : '',
    blockingSeverities: Array.isArray(blocking)
      ? blocking.map((item) => String(item)).join(', ')
      : '',
  }
}

export function computeFormFromDocument(
  document: Record<string, unknown>,
): ComputePolicyFormFields {
  return {
    version: typeof document.version === 'string' ? document.version : '',
    provider: typeof document.provider === 'string' ? document.provider : '',
    model: typeof document.model === 'string' ? document.model : '',
  }
}

export function applyReviewFormToDocument(
  document: Record<string, unknown>,
  form: ReviewPolicyFormFields,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...document }
  next.version = form.version.trim()
  next.blocking_severities = form.blockingSeverities
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
  return next
}

export function applyComputeFormToDocument(
  document: Record<string, unknown>,
  form: ComputePolicyFormFields,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...document }
  next.version = form.version.trim()
  next.provider = form.provider.trim()
  next.model = form.model.trim()
  return next
}

export function stringifyPolicyDocument(document: Record<string, unknown>): string {
  return stringifyYaml(document, { lineWidth: 0 })
}

export function patchPolicyTextFromReviewForm(
  text: string,
  form: ReviewPolicyFormFields,
): string {
  return stringifyPolicyDocument(applyReviewFormToDocument(parsePolicyDocument(text), form))
}

export function patchPolicyTextFromComputeForm(
  text: string,
  form: ComputePolicyFormFields,
): string {
  return stringifyPolicyDocument(applyComputeFormToDocument(parsePolicyDocument(text), form))
}
