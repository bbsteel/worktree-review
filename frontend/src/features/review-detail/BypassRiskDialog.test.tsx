/**
 * B-300: the per-finding Accept-risk dialog submits through the real data
 * source. No simulation: success calls back for a refetch, 409 asks for a
 * refreshed state, 503 preserves the typed reason, and 401 points at
 * re-authentication.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { DataSourceContext } from '../../app/data-source.ts'
import { ApiError } from '../../data/api/review-api-client.ts'
import { blockedCase } from '../../data/fixtures/index.ts'
import type { BypassSubmissionView } from '../../domain/audit.ts'
import type { ReviewDataSource } from '../../data/sources/review-data-source.ts'
import type { ReviewFindingView, ReviewRunView } from '../../domain/review.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { BypassRiskDialog } from './BypassRiskDialog.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

const SUBMITTED: BypassSubmissionView = {
  bypassId: 42,
  bypassState: 'active',
  standingGateState: 'Blocked',
  remainingBlockingCount: 1,
  standingRevision: 4,
  checkSyncStatus: 'queued',
  gateTransitioned: false,
  replayed: false,
}

function blockingFinding(): ReviewFindingView {
  const finding = blockedCase.findings.find((candidate) => candidate.blocking)
  if (finding === undefined) throw new Error('blockedCase has no blocking finding')
  return finding
}

function runWithCapability(): ReviewRunView {
  return {
    ...structuredClone(blockedCase),
    bypassCapability: 'available',
    gate: {
      ...structuredClone(blockedCase.gate),
      remainingBlockingFingerprints: blockedCase.findings
        .filter((finding) => finding.blocking)
        .map((finding) => finding.fingerprint),
    },
  }
}

function sourceWith(bypassFinding: ReviewDataSource['bypassFinding']): {
  source: ReviewDataSource
  calls: Array<[string, string, string]>
} {
  const calls: Array<[string, string, string]> = []
  const source: ReviewDataSource = {
    kind: 'live',
    environmentBadge: null,
    getOverview: () => Promise.reject(new Error('not used')),
    getReviewRun: () => Promise.reject(new Error('not used')),
    listCases: () => Promise.resolve([]),
    getCase: () => Promise.reject(new Error('not used')),
    bypassFinding:
      bypassFinding ??
      ((attemptId, fingerprint, reason) => {
        calls.push([attemptId, fingerprint, reason])
        return Promise.resolve(SUBMITTED)
      }),
  }
  return { source, calls }
}

function renderDialog(
  source: ReviewDataSource,
  onSubmitted = vi.fn(),
  onClose = vi.fn(),
  onConflict = vi.fn(),
) {
  const run = runWithCapability()
  const finding = blockingFinding()
  render(
    <DataSourceContext.Provider
      value={{ source, overview: null, cases: [], loading: false, error: null, authSession: null }}
    >
      <BypassRiskDialog
        open
        run={run}
        finding={finding}
        onClose={onClose}
        onSubmitted={onSubmitted}
        onConflict={onConflict}
      />
    </DataSourceContext.Provider>,
  )
  return { run, finding, onSubmitted, onClose, onConflict }
}

describe('BypassRiskDialog (real submission)', () => {
  it('frames risk acceptance, requires a reason, and submits per finding', async () => {
    const { source, calls } = sourceWith(undefined)
    const { run, finding, onSubmitted, onClose } = renderDialog(source)
    const user = userEvent.setup()

    const dialog = screen.getByRole('dialog', { name: 'Accept the risk of this finding?' })
    expect(within(dialog).getByText(/accepting the risk/)).toBeInTheDocument()
    expect(within(dialog).getByText(/does not mean the finding was resolved/)).toBeInTheDocument()
    expect(within(dialog).getByText(new RegExp(finding.fingerprint))).toBeInTheDocument()

    const confirm = within(dialog).getByRole('button', { name: 'Accept risk' })
    expect(confirm).toBeDisabled()

    await user.type(within(dialog).getByRole('textbox'), 'Isolated endpoint; removal scheduled.')
    expect(confirm).toBeEnabled()
    await user.click(confirm)

    expect(calls).toEqual([[run.attemptId, finding.fingerprint, 'Isolated endpoint; removal scheduled.']])
    expect(onSubmitted).toHaveBeenCalledWith(SUBMITTED)
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps the typed reason on 503 so the user can retry', async () => {
    const { source } = sourceWith(() =>
      Promise.reject(new ApiError('audit_store_unavailable', 'store down', 503)),
    )
    renderDialog(source)
    const user = userEvent.setup()

    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'keep me')
    await user.click(within(dialog).getByRole('button', { name: 'Accept risk' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/reason is preserved/i)
    expect(within(dialog).getByRole('textbox')).toHaveValue('keep me')
  })

  it('409 closes the stale context and asks the parent to refetch', async () => {
    const { source } = sourceWith(() =>
      Promise.reject(new ApiError('bypass_not_standing', 'stale', 409)),
    )
    const onConflict = vi.fn()
    renderDialog(source, vi.fn(), vi.fn(), onConflict)
    const user = userEvent.setup()
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'reason')
    await user.click(within(dialog).getByRole('button', { name: 'Accept risk' }))
    // The stale confirmation never lingers: the parent closes and refetches.
    await vi.waitFor(() => expect(onConflict).toHaveBeenCalledOnce())
  })

  it('treats a client-mapped Bypass 409 (ApiError) as conflict, not a stuck dialog', async () => {
    // Mirrors ReviewApiClient: non-idempotency 409s stay ApiError with httpStatus.
    const conflict = new ApiError('bypass_policy_changed', 'policy moved', 409)
    const { source } = sourceWith(() => Promise.reject(conflict))
    const onConflict = vi.fn()
    const onClose = vi.fn()
    renderDialog(source, vi.fn(), onClose, onConflict)
    const user = userEvent.setup()
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'reason after drift')
    await user.click(within(dialog).getByRole('button', { name: 'Accept risk' }))
    await vi.waitFor(() => expect(onConflict).toHaveBeenCalledOnce())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('401 offers a real sign-in entry point', async () => {
    const { source } = sourceWith(() =>
      Promise.reject(new ApiError('session_expired', 'expired', 401)),
    )
    renderDialog(source)
    const user = userEvent.setup()
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'reason')
    await user.click(within(dialog).getByRole('button', { name: 'Accept risk' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(/session expired/i)
    expect(within(alert).getByRole('link', { name: 'Sign in with GitHub' })).toHaveAttribute(
      'href',
      '/api/v1/auth/github/start',
    )
  })

  it('never submits when the data source has no bypass capability', async () => {
    const { source } = sourceWith(undefined)
    delete source.bypassFinding
    renderDialog(source)
    const user = userEvent.setup()
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByRole('textbox'), 'reason')
    await user.click(within(dialog).getByRole('button', { name: 'Accept risk' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/could not decide/i)
  })
})
