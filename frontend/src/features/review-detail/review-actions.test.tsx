/**
 * B-014 target interactions for Retry and Bypass.
 *
 * The shipped demo fixtures keep every remote action disabled with an honest
 * Pre-Alpha reason, so these tests derive runs with the capability explicitly
 * enabled — the same deterministic override pattern as the state matrix.
 * Confirming in this prototype must never send a remote request; each test
 * asserts fetch was not called.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  blockedCase,
  errorMergeConflictCase,
  passedCase,
} from '../../data/fixtures/index.ts'
import type { AvailableReviewActionsView, ReviewRunView } from '../../domain/review.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { AttemptsTab } from './AttemptsTab.tsx'
import { ReviewActionsBar } from './ReviewActionsBar.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

let fetchSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, 'fetch')
})

afterEach(() => {
  fetchSpy.mockRestore()
})

function derive(overrides: Partial<ReviewRunView>): ReviewRunView {
  return { ...structuredClone(blockedCase), ...overrides }
}

function withActions(run: ReviewRunView, actions: Partial<AvailableReviewActionsView>): ReviewRunView {
  return { ...run, availableActions: { ...run.availableActions, ...actions } }
}

const enabled = { visible: true, enabled: true, disabledReason: null }

describe('Retry confirmation', () => {
  it('github authoritative retry copy states the standing decision is revoked', async () => {
    const run = withActions(derive({}), { retry: enabled })
    const user = userEvent.setup()
    render(<ReviewActionsBar run={run} />)

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    const dialog = screen.getByRole('dialog', { name: 'Retry this review?' })
    expect(within(dialog).getByText(/temporarily revokes the current standing decision/)).toBeInTheDocument()
    expect(within(dialog).getByText(/superseded history and is never overwritten/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: /Create new attempt/ }))
    expect(screen.getByRole('status')).toHaveTextContent(/simulated locally/i)
    expect(screen.getByRole('status')).toHaveTextContent(/sent no request/i)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('local retry copy never mentions a standing decision', async () => {
    const run = withActions(structuredClone(passedCase), { retry: enabled })
    const user = userEvent.setup()
    render(<ReviewActionsBar run={run} />)

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    const dialog = screen.getByRole('dialog', { name: 'Retry this review?' })
    expect(within(dialog).getByText(/creates a new local attempt/)).toBeInTheDocument()
    expect(dialog).not.toHaveTextContent(/standing decision/)

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('disabled retry shows its reason and never opens the dialog', async () => {
    const user = userEvent.setup()
    render(<ReviewActionsBar run={derive({})} />)

    const retryButton = screen.getByRole('button', { name: 'Retry' })
    expect(retryButton).toBeDisabled()
    expect(screen.getByLabelText(/Retry unavailable:/)).toBeInTheDocument()

    await user.click(retryButton)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('Bypass risk confirmation', () => {
  it('jump entry routes to the per-finding actions and never submits', async () => {
    const run = withActions(derive({}), { bypass: enabled })
    const user = userEvent.setup()
    const onShowFindings = vi.fn()
    render(<ReviewActionsBar run={run} onShowFindings={onShowFindings} />)

    await user.click(screen.getByRole('button', { name: 'Bypass' }))

    // P3: the bar is only a jump entry. Risk is accepted per finding through
    // the real API in the Findings tab — never by one whole-gate click.
    expect(onShowFindings).toHaveBeenCalledOnce()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('bypass stays hidden for the error case', () => {
    render(<ReviewActionsBar run={structuredClone(errorMergeConflictCase)} />)
    expect(screen.queryByRole('button', { name: 'Bypass' })).not.toBeInTheDocument()
  })

  it('bypass stays hidden for local one-shot results', () => {
    render(<ReviewActionsBar run={structuredClone(passedCase)} />)
    expect(screen.queryByRole('button', { name: 'Bypass' })).not.toBeInTheDocument()
  })
})

describe('Attempt timeline transition', () => {
  it('renders a newly added attempt without removing history', () => {
    const run = derive({})
    const { rerender } = render(<AttemptsTab run={run} />)
    const originalCount = run.attempts.length

    const retried = structuredClone(run)
    retried.attempts = retried.attempts.map((attempt) => ({
      ...attempt,
      authority: 'superseded' as const,
    }))
    retried.attempts.unshift({
      ...retried.attempts[0],
      attemptId: 'attempt_01JY8SIMULATED0',
      authority: 'authoritative' as const,
      trigger: 'github-retry-requested-action',
    })
    retried.attemptId = 'attempt_01JY8SIMULATED0'

    rerender(<AttemptsTab run={retried} />)

    expect(screen.getAllByRole('listitem')).toHaveLength(originalCount + 1)
    expect(screen.getByText('attempt_01JY8SIMULATED0')).toBeInTheDocument()
    // The superseded attempt keeps its loss-of-authority explanation.
    expect(screen.getAllByText(/no longer governs|Superseded/i).length).toBeGreaterThan(0)
  })
})
