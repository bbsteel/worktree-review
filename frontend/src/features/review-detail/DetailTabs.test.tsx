import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import {
  blockedCase,
  errorMergeConflictCase,
  passedCase,
} from '../../data/fixtures/index.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { AttemptsTab } from './AttemptsTab.tsx'
import { CoverageTab } from './CoverageTab.tsx'
import { IdentityTab } from './IdentityTab.tsx'
import { PoliciesTab } from './PoliciesTab.tsx'
import { UsageTab } from './UsageTab.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

describe('CoverageTab', () => {
  it('shows complete required coverage with counts', () => {
    render(<CoverageTab run={blockedCase} />)

    expect(screen.getByText('Required Coverage')).toBeInTheDocument()
    expect(screen.getByText('Complete')).toBeInTheDocument()
    expect(screen.getByText(/48 reviewed · 0 missing · 2 excluded/)).toBeInTheDocument()
  })

  it('groups files by category with reasons and rules', () => {
    render(<CoverageTab run={blockedCase} />)

    const excluded = screen.getByRole('region', { name: 'Excluded files' })
    expect(within(excluded).getByText('vendor/stripe-sdk/**')).toBeInTheDocument()
    expect(
      within(excluded).getByText(/Third-party vendored code is excluded/),
    ).toBeInTheDocument()
    expect(within(excluded).getByText('rule: excluded-glob: vendor/**')).toBeInTheDocument()
  })

  it('explains an error gate instead of hiding missing content behind a percentage', () => {
    render(<CoverageTab run={errorMergeConflictCase} />)

    expect(screen.getByText('Incomplete')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/Gate cannot pass/)
    expect(screen.getByRole('alert')).toHaveTextContent(/Construct Merge/)

    const unreviewable = screen.getByRole('region', { name: 'Unreviewable files' })
    expect(
      within(unreviewable).getByText(/merge tree was not constructed/),
    ).toBeInTheDocument()
  })

  it('says when the schema did not report a reason instead of guessing', () => {
    const withoutReason = structuredClone(blockedCase)
    const target = withoutReason.coverage.files.find((file) => file.category === 'excluded')
    if (target) {
      target.reason = null
    }
    render(<CoverageTab run={withoutReason} />)

    expect(screen.getByText('Reason not reported by this result schema.')).toBeInTheDocument()
  })
})

describe('AttemptsTab', () => {
  it('renders the current attempt with authority and gate', () => {
    render(<AttemptsTab run={blockedCase} />)

    expect(screen.getByText('Current attempt')).toBeInTheDocument()
    expect(screen.getByText('Authoritative attempt')).toBeInTheDocument()
    expect(screen.getAllByText('attempt_01JY8R7F2W').length).toBeGreaterThan(0)
    expect(screen.getByText('review 1.3.0 · compute 2.1.0')).toBeInTheDocument()
    expect(screen.getByText('37,000')).toBeInTheDocument()
    expect(screen.getByText('$0.42')).toBeInTheDocument()
  })

  it('marks superseded attempts as stripped of gate authority', () => {
    const withSuperseded = structuredClone(blockedCase)
    const previous = withSuperseded.attempts[0]
    if (previous) {
      withSuperseded.attempts = [
        { ...previous, attemptId: 'attempt_01JY8OLD00', authority: 'superseded', gateState: 'blocked' },
        previous,
      ]
    }
    render(<AttemptsTab run={withSuperseded} />)

    expect(screen.getByText('Superseded')).toBeInTheDocument()
    expect(
      screen.getByText(/can no longer publish or change the standing decision/i),
    ).toBeInTheDocument()
  })

  it('shows an explicit empty state when no attempts are recorded', () => {
    const withoutAttempts = structuredClone(passedCase)
    withoutAttempts.attempts = []
    render(<AttemptsTab run={withoutAttempts} />)

    expect(screen.getByText('No attempts recorded')).toBeInTheDocument()
  })
})

describe('IdentityTab', () => {
  it('shows the full identity chain for a constructed merge', () => {
    render(<IdentityTab run={blockedCase} />)

    expect(screen.getByText('github:acme/payment-service#184')).toBeInTheDocument()
    expect(screen.getAllByText(/Review Request Key/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Merge Tree OID/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Review Identity/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Standing Decision/)).toBeInTheDocument()
  })

  it('never fabricates a review identity when the merge was not constructed', () => {
    render(<IdentityTab run={errorMergeConflictCase} />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Review identity unavailable — merge candidate was not constructed.',
    )
    expect(screen.getByText('Not constructed')).toBeInTheDocument()
    expect(screen.getByText('Unavailable — see the notice above')).toBeInTheDocument()
    // The fixture still knows the requested refs; only merge-derived values are absent.
    expect(screen.getByText('local:acme/demo-invalid-config:main:feature/broken-merge'))
      .toBeInTheDocument()
  })
})

describe('PoliciesTab', () => {
  it('shows the attempt policy snapshots with hashes and disclosure', () => {
    render(<PoliciesTab run={blockedCase} />)

    expect(screen.getByText(/default-review 1.3.0/)).toBeInTheDocument()
    expect(screen.getByText(/openai-gpt-5.6 2.1.0/)).toBeInTheDocument()
    expect(screen.getByText(/OpenAI API \(United States\)/)).toBeInTheDocument()
    expect(screen.getByText(/30 days for API abuse monitoring/)).toBeInTheDocument()
    expect(screen.getByText(/pcfg_openai_api_2026_09_01/)).toBeInTheDocument()
  })

  it('keeps the trust boundary note', () => {
    render(<PoliciesTab run={blockedCase} />)

    expect(screen.getByText(/outside the reviewed repository/)).toBeInTheDocument()
    expect(screen.getByText(/cannot change gate rules/)).toBeInTheDocument()
  })
})

describe('UsageTab', () => {
  it('separates estimated and actual cost', () => {
    render(<UsageTab run={blockedCase} />)

    expect(screen.getByText('Estimated cost')).toBeInTheDocument()
    expect(screen.getByText('Actual cost')).toBeInTheDocument()
    expect(screen.getByText('$0.40')).toBeInTheDocument()
    expect(screen.getByText('$0.42')).toBeInTheDocument()
    expect(screen.getByText('32,800')).toBeInTheDocument()
    expect(screen.getByText('4,200')).toBeInTheDocument()
  })

  it('lists per-call details with ordinal, dimension, elapsed and cost', () => {
    render(<UsageTab run={blockedCase} />)

    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(5)
    expect(within(table).getByText('#1')).toBeInTheDocument()
    expect(within(table).getByText('security')).toBeInTheDocument()
    expect(within(table).getAllByText('dimension-review').length).toBe(4)
    expect(within(table).getByText('$0.16')).toBeInTheDocument()
  })

  it('shows unknown usage as Unknown with a reason, never as $0.00', () => {
    render(<UsageTab run={errorMergeConflictCase} />)

    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
    expect(screen.getByText(/the provider did not report a price/)).toBeInTheDocument()
    expect(screen.getByText(/No provider calls were recorded/)).toBeInTheDocument()
  })

  it('renders Not reported for missing call identity instead of guessing', () => {
    const missingIdentity = structuredClone(blockedCase)
    const firstCall = missingIdentity.usage.calls[0]
    if (firstCall) {
      firstCall.ordinal = null
      firstCall.dimensionId = null
      firstCall.elapsedMs = null
    }
    render(<UsageTab run={missingIdentity} />)

    expect(screen.getAllByText('Not reported').length).toBe(3)
  })
})
