import { describe, expect, it } from 'vitest'
import {
  buildCreateReviewRequest,
  describeSourceSelection,
  INITIAL_NEW_REVIEW_FORM,
  validateNewReviewForm,
  type NewReviewFormState,
} from './new-review-form.ts'

function validForm(overrides: Partial<NewReviewFormState> = {}): NewReviewFormState {
  return {
    ...INITIAL_NEW_REVIEW_FORM,
    repositoryId: 'repo_1',
    reviewPolicyId: 'rp_default',
    computePolicyId: 'cp_gpt',
    ...overrides,
  }
}

describe('validateNewReviewForm', () => {
  it('requires repository, review policy and compute policy', () => {
    const errors = validateNewReviewForm(INITIAL_NEW_REVIEW_FORM)
    expect(errors.repositoryId).toBeTruthy()
    expect(errors.reviewPolicyId).toBeTruthy()
    expect(errors.computePolicyId).toBeTruthy()
  })

  it('accepts a minimal current-worktree form', () => {
    expect(validateNewReviewForm(validForm())).toEqual({})
  })

  it('requires a non-negative integer commit count in recent-commits mode', () => {
    for (const bad of ['', '-1', '1.5', 'abc']) {
      const errors = validateNewReviewForm(
        validForm({ sourceMode: 'local-recent-commits', commitCount: bad }),
      )
      expect(errors.commitCount).toBeTruthy()
    }
    expect(
      validateNewReviewForm(validForm({ sourceMode: 'local-recent-commits', commitCount: '3' })),
    ).toEqual({})
  })

  it('requires a proposed ref in committed-ref mode', () => {
    const errors = validateNewReviewForm(
      validForm({ sourceMode: 'local-committed-ref', proposedRef: '  ' }),
    )
    expect(errors.proposedRef).toBeTruthy()
  })
})

describe('buildCreateReviewRequest', () => {
  it('omits empty target ref instead of sending an empty string', () => {
    const request = buildCreateReviewRequest(validForm())
    expect(request.source).toEqual({ kind: 'local-worktree' })
  })

  it('includes an explicit target ref when given', () => {
    const request = buildCreateReviewRequest(validForm({ targetRef: 'release/1.4' }))
    expect(request.source).toEqual({ kind: 'local-worktree', target_ref: 'release/1.4' })
  })

  it('builds the recent-commits union variant with a numeric count', () => {
    const request = buildCreateReviewRequest(
      validForm({ sourceMode: 'local-recent-commits', commitCount: '5' }),
    )
    expect(request.source).toEqual({ kind: 'local-recent-commits', commit_count: 5 })
  })

  it('builds the committed-ref variant with proposed and optional target', () => {
    const request = buildCreateReviewRequest(
      validForm({
        sourceMode: 'local-committed-ref',
        proposedRef: 'feature/webhook-auth',
        targetRef: 'main',
      }),
    )
    expect(request.source).toEqual({
      kind: 'local-committed-ref',
      proposed_ref: 'feature/webhook-auth',
      target_ref: 'main',
    })
  })
})

describe('describeSourceSelection', () => {
  it('derives HEAD~N for recent-commits mode', () => {
    expect(
      describeSourceSelection(
        validForm({ sourceMode: 'local-recent-commits', commitCount: '4' }),
      ),
    ).toEqual({ target: 'HEAD~4', proposed: 'WORKTREE' })
  })

  it('defaults target to HEAD', () => {
    expect(describeSourceSelection(validForm())).toEqual({
      target: 'HEAD',
      proposed: 'WORKTREE',
    })
  })
})
