import { describe, expect, it } from 'vitest'
import {
  applyComputeFormToDocument,
  applyReviewFormToDocument,
  parsePolicyDocument,
  patchPolicyTextFromReviewForm,
  stringifyPolicyDocument,
} from './policy-document-sync.ts'

describe('policy-document-sync', () => {
  it('preserves unknown YAML keys when applying the review form subset', () => {
    const original = `schema: worktree-review.review-policy/v1
version: 0.1.0
required_dimensions:
  - correctness
blocking_severities:
  - critical
custom_extension:
  keep: true
`
    const patched = patchPolicyTextFromReviewForm(original, {
      version: '0.2.0',
      blockingSeverities: 'critical, major',
    })
    const document = parsePolicyDocument(patched)
    expect(document.version).toBe('0.2.0')
    expect(document.blocking_severities).toEqual(['critical', 'major'])
    expect(document.required_dimensions).toEqual(['correctness'])
    expect(document.custom_extension).toEqual({ keep: true })
    expect(document).not.toHaveProperty('name')
  })

  it('does not invent a schema-forbidden name field', () => {
    const reviewDocument = parsePolicyDocument(`schema: worktree-review.review-policy/v1
version: 0.1.0
blocking_severities:
  - critical
`)
    const reviewNext = applyReviewFormToDocument(reviewDocument, {
      version: '0.1.1',
      blockingSeverities: 'major',
    })
    expect(reviewNext).not.toHaveProperty('name')
    expect(reviewNext.version).toBe('0.1.1')

    const computeDocument = parsePolicyDocument(`schema: worktree-review.compute-policy/v1
version: 0.1.0
provider: anthropic
model: claude-sonnet-4-5
`)
    const computeNext = applyComputeFormToDocument(computeDocument, {
      version: '0.1.1',
      provider: 'openai',
      model: 'gpt-5',
    })
    expect(computeNext).not.toHaveProperty('name')
    expect(computeNext.provider).toBe('openai')
  })

  it('applies compute form fields without dropping destination disclosure', () => {
    const document = parsePolicyDocument(`schema: worktree-review.compute-policy/v1
version: 0.1.0
provider: anthropic
model: claude-sonnet-4-5
data_destination: https://api.anthropic.com
known_retention: keep
`)
    const next = applyComputeFormToDocument(document, {
      version: '0.1.1',
      provider: 'openai',
      model: 'gpt-5',
    })
    expect(next.provider).toBe('openai')
    expect(next.model).toBe('gpt-5')
    expect(next.data_destination).toBe('https://api.anthropic.com')
    expect(stringifyPolicyDocument(next)).toContain('data_destination:')
  })
})
