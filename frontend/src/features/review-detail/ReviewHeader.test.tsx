import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { blockedCase, errorMergeConflictCase, passedCase } from '../../data/fixtures/index.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { ReviewHeader } from './ReviewHeader.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

describe('ReviewHeader with a GitHub pull request source', () => {
  it('renders repository, PR number and title with the blocked gate', () => {
    render(<ReviewHeader run={blockedCase} />)

    expect(
      screen.getByRole('heading', { name: 'acme/payment-service · PR #184' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Harden webhook authorization')).toBeInTheDocument()
    expect(screen.getByText('feature/webhook-auth → main')).toBeInTheDocument()
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Authoritative attempt')).toBeInTheDocument()
    expect(screen.getByText('ada')).toBeInTheDocument()
  })

  it('shows provider, policy, attempt, duration and cost metadata', () => {
    render(<ReviewHeader run={blockedCase} />)

    expect(screen.getByText('openai / gpt-5.6')).toBeInTheDocument()
    expect(screen.getByText('1.3.0')).toBeInTheDocument()
    expect(screen.getByText('attempt_01JY8R7F2W')).toBeInTheDocument()
    expect(screen.getByText('2m 18s')).toBeInTheDocument()
    expect(screen.getByText('$0.42')).toBeInTheDocument()
  })

  it('never renders local worktree fields for GitHub sources', () => {
    render(<ReviewHeader run={blockedCase} />)

    expect(screen.queryByText('WORKTREE')).not.toBeInTheDocument()
    expect(screen.queryByText('Snapshot')).not.toBeInTheDocument()
  })

  it('shows all four GitHub actions disabled with their reasons', async () => {
    const user = userEvent.setup()
    render(<ReviewHeader run={blockedCase} />)

    for (const label of ['Retry', 'Bypass', 'Open Check', 'Open Session Insight']) {
      const button = screen.getByRole('button', { name: label })
      expect(button).toBeDisabled()
    }

    const bypassReason = screen.getByLabelText(/Bypass unavailable:/)
    await user.hover(bypassReason)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Bypass means accepting the risk. It does not mean the finding was resolved.',
    )
  })

  it('keeps the retry standing-decision warning on GitHub sources', () => {
    render(<ReviewHeader run={blockedCase} />)

    expect(screen.getByLabelText(/Retry unavailable:/)).toHaveAttribute(
      'aria-label',
      expect.stringContaining('temporarily revoke the current standing decision'),
    )
  })
})

describe('ReviewHeader with a local worktree source', () => {
  it('renders the local one-shot identity without GitHub fields', () => {
    render(<ReviewHeader run={passedCase} />)

    expect(screen.getByRole('heading', { name: 'acme/session-insight' })).toBeInTheDocument()
    expect(screen.getByText('Passed')).toBeInTheDocument()
    expect(screen.getByText('Local one-shot result')).toBeInTheDocument()
    expect(screen.getByText('main → WORKTREE')).toBeInTheDocument()

    expect(screen.queryByText(/^Author$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/PR #/)).not.toBeInTheDocument()
    expect(screen.queryByText(/standing decision/i)).toBeInTheDocument()
  })

  it('hides the Bypass action for local one-shot results', () => {
    render(<ReviewHeader run={passedCase} />)

    expect(screen.queryByRole('button', { name: 'Bypass' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open Check' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled()
  })

  it('explains that local retry only creates a new attempt', () => {
    render(<ReviewHeader run={passedCase} />)

    expect(screen.getByLabelText(/Retry unavailable:/)).toHaveAttribute(
      'aria-label',
      expect.stringContaining('creates a new local attempt'),
    )
  })
})

describe('ReviewHeader with an error run', () => {
  it('shows the Error gate and the failed run status with text', () => {
    render(<ReviewHeader run={errorMergeConflictCase} />)

    expect(screen.getByText('Error')).toBeInTheDocument()
    expect(screen.getByText(/Run status: Failed/)).toBeInTheDocument()
    expect(screen.getByText(/the outcome for the code is unknown/i)).toBeInTheDocument()
  })

  it('shows unknown cost as Unknown, not zero', () => {
    render(<ReviewHeader run={errorMergeConflictCase} />)

    const metadata = screen.getByText('Cost').parentElement
    expect(metadata).not.toBeNull()
    expect(within(metadata as HTMLElement).getByText('Unknown')).toBeInTheDocument()
  })
})

describe('CopyValue in the header', () => {
  it('copies the full attempt id', async () => {
    const user = userEvent.setup()
    render(<ReviewHeader run={blockedCase} />)

    await user.click(screen.getByRole('button', { name: 'Copy Attempt ID' }))
    expect(await navigator.clipboard.readText()).toBe('attempt_01JY8R7F2W')
  })
})
