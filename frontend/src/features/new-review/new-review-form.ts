/**
 * Pure form model for the New Review page (design 11). Field visibility and
 * validation follow the source-mode table exactly; building the request is
 * separate from validation so tests can pin both.
 */
import type { CreateReviewRequestDto } from '../../data/api/dto.ts'

export type ReviewSourceMode = 'local-worktree' | 'local-recent-commits' | 'local-committed-ref'

export interface NewReviewFormState {
  repositoryId: string
  sourceMode: ReviewSourceMode
  /** local-worktree / local-committed-ref: optional, defaults to HEAD. */
  targetRef: string
  /** local-recent-commits: required, N >= 0. */
  commitCount: string
  /** local-committed-ref: required. */
  proposedRef: string
  reviewPolicyId: string
  computePolicyId: string
}

export const INITIAL_NEW_REVIEW_FORM: NewReviewFormState = {
  repositoryId: '',
  sourceMode: 'local-worktree',
  targetRef: '',
  commitCount: '',
  proposedRef: '',
  reviewPolicyId: '',
  computePolicyId: '',
}

/** Field key → human-readable error. Empty object means valid. */
export type NewReviewFormErrors = Partial<Record<keyof NewReviewFormState, string>>

export function validateNewReviewForm(state: NewReviewFormState): NewReviewFormErrors {
  const errors: NewReviewFormErrors = {}

  if (state.repositoryId === '') {
    errors.repositoryId = 'Select an authorized repository.'
  }
  if (state.reviewPolicyId === '') {
    errors.reviewPolicyId = 'Select a Review Policy.'
  }
  if (state.computePolicyId === '') {
    errors.computePolicyId = 'Select a Compute Policy.'
  }

  if (state.sourceMode === 'local-recent-commits') {
    const parsed = Number(state.commitCount)
    if (state.commitCount.trim() === '' || !Number.isInteger(parsed) || parsed < 0) {
      errors.commitCount = 'Commit count is required and must be an integer ≥ 0.'
    }
  }

  if (state.sourceMode === 'local-committed-ref' && state.proposedRef.trim() === '') {
    errors.proposedRef = 'A committed proposed ref is required for this source mode.'
  }

  return errors
}

/**
 * Build the create-review request. Source is a discriminated union; fields
 * that do not apply to the selected mode are omitted, never sent empty.
 */
export function buildCreateReviewRequest(
  state: NewReviewFormState,
): CreateReviewRequestDto {
  const targetRef = state.targetRef.trim()
  let source: CreateReviewRequestDto['source']

  switch (state.sourceMode) {
    case 'local-worktree':
      source = targetRef === '' ? { kind: 'local-worktree' } : { kind: 'local-worktree', target_ref: targetRef }
      break
    case 'local-recent-commits':
      source = { kind: 'local-recent-commits', commit_count: Number(state.commitCount) }
      break
    case 'local-committed-ref': {
      source = {
        kind: 'local-committed-ref',
        proposed_ref: state.proposedRef.trim(),
        ...(targetRef === '' ? {} : { target_ref: targetRef }),
      }
      break
    }
  }

  return {
    repository_id: state.repositoryId,
    source,
    review_policy_id: state.reviewPolicyId,
    compute_policy_id: state.computePolicyId,
  }
}

/** Derived display value: recent-commits mode reviews HEAD~N → WORKTREE. */
export function describeSourceSelection(state: NewReviewFormState): {
  target: string
  proposed: string
} {
  switch (state.sourceMode) {
    case 'local-worktree':
      return { target: state.targetRef.trim() || 'HEAD', proposed: 'WORKTREE' }
    case 'local-recent-commits': {
      const parsed = Number(state.commitCount)
      const count = Number.isInteger(parsed) && parsed >= 0 ? parsed : 0
      return { target: `HEAD~${count}`, proposed: 'WORKTREE' }
    }
    case 'local-committed-ref':
      return {
        target: state.targetRef.trim() || 'HEAD',
        proposed: state.proposedRef.trim() || '(required)',
      }
  }
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
