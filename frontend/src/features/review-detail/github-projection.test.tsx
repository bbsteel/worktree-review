/**
 * B-204 GitHub live UI projection (design 20.4): PR source, Check link,
 * authority/publication display, and retry guidance. The single-user web
 * deployment never acts as a GitHub actor — authorized retry is always
 * guided to the GitHub Checks requested action.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { blockedCase, passedCase } from '../../data/fixtures/index.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { AttemptsTab } from './AttemptsTab.tsx'
import { ReviewActionsBar } from './ReviewActionsBar.tsx'
import { ReviewHeader } from './ReviewHeader.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

function githubRun(overrides: Partial<ReviewRunView> = {}): ReviewRunView {
  return { ...structuredClone(blockedCase), ...overrides }
}

describe('GitHub Check link projection', () => {
  it('renders a real Check link with destination host when enabled', () => {
    const run = githubRun()
    if (run.source.kind === 'github-pull-request') {
      run.source.checkUrl = 'https://github.com/acme/payment-service/runs/987654'
    }
    run.availableActions.openCheck = { visible: true, enabled: true, disabledReason: null }
    run.publicationStatus = 'published'

    render(<ReviewActionsBar run={run} />)

    const link = screen.getByRole('link', { name: /Open Check/ })
    expect(link).toHaveAttribute('href', 'https://github.com/acme/payment-service/runs/987654')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(link.textContent).toContain('github.com')
  })

  it('stays disabled with a reason when enabled but no Check URL was recorded', () => {
    const run = githubRun()
    run.availableActions.openCheck = { visible: true, enabled: true, disabledReason: null }

    render(<ReviewActionsBar run={run} />)

    expect(screen.queryByRole('link', { name: /Open Check/ })).not.toBeInTheDocument()
    expect(
      screen.getByLabelText(/Open Check unavailable: No GitHub Check URL was recorded/),
    ).toBeInTheDocument()
  })

  it('shows the publication status in the header when a Check was published', () => {
    const run = githubRun({ publicationStatus: 'published' })
    render(<ReviewHeader run={run} />)

    expect(screen.getByText('Check published')).toBeInTheDocument()
  })

  it('shows publication failure without rewriting the gate', () => {
    const run = githubRun({ publicationStatus: 'failed' })
    render(<ReviewHeader run={run} />)

    expect(screen.getByText('Check publication failed')).toBeInTheDocument()
    expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0)
  })
})

describe('GitHub authority and retry guidance', () => {
  it('guides authorized retry to the GitHub Checks requested action', () => {
    render(<AttemptsTab run={githubRun()} />)

    expect(
      screen.getByText(/Authorized retry runs from the GitHub Checks requested action/),
    ).toBeInTheDocument()
    expect(screen.getByText(/cannot prove a GitHub actor/)).toBeInTheDocument()
  })

  it('states that a superseded attempt can never overwrite the standing decision', () => {
    const run = githubRun({ authority: 'superseded' })
    render(<AttemptsTab run={run} />)

    expect(screen.getByText(/can never overwrite the current standing decision/)).toBeInTheDocument()
  })

  it('does not show GitHub retry guidance on local sources', () => {
    render(<AttemptsTab run={passedCase} />)

    expect(
      screen.queryByText(/GitHub Checks requested action/),
    ).not.toBeInTheDocument()
  })

  it('keeps web Retry disabled so the browser cannot act as a GitHub actor', () => {
    render(<ReviewActionsBar run={githubRun()} />)

    const retry = screen.getByRole('button', { name: 'Retry' })
    expect(retry).toBeDisabled()
    expect(screen.getByLabelText(/Retry unavailable:/)).toHaveAttribute(
      'aria-label',
      expect.stringContaining('temporarily revoke the current standing decision'),
    )
  })

  it('renders the PR source identity in the shared detail header', () => {
    render(<ReviewHeader run={githubRun()} />)

    expect(
      screen.getByRole('heading', { name: 'acme/payment-service · PR #184' }),
    ).toBeInTheDocument()
    expect(screen.getByText('feature/webhook-auth → main')).toBeInTheDocument()
    expect(screen.getByText('ada')).toBeInTheDocument()
  })
})
