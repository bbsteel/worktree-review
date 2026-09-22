import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { SessionInsightStatusView } from '../../domain/overview.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { SessionInsightCard } from './SessionInsightCard.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function status(overrides: Partial<SessionInsightStatusView>): SessionInsightStatusView {
  return {
    state: 'disconnected',
    currentAttemptId: null,
    childSessionCount: 0,
    lastProbeAt: null,
    ...overrides,
  }
}

describe('SessionInsightCard', () => {
  it('renders all four connection states with distinct labels', () => {
    for (const [state, label] of [
      ['connected', 'Connected'],
      ['disconnected', 'Disconnected'],
      ['incompatible', 'Version incompatible'],
      ['disabled', 'Observation disabled'],
    ] as const) {
      const { unmount } = render(<SessionInsightCard status={status({ state })} />)
      expect(screen.getByText(label)).toBeInTheDocument()
      unmount()
    }
  })

  it('shows probe time and child session count when connected', () => {
    render(
      <SessionInsightCard
        status={status({
          state: 'connected',
          currentAttemptId: 'attempt_01JABC',
          childSessionCount: 6,
          lastProbeAt: '2026-09-09T14:12:00.000Z',
        })}
      />,
    )

    expect(screen.getByText(/Last probed 2026-09-09 14:12:00 UTC/)).toBeInTheDocument()
    expect(screen.getByText('attempt_01JABC')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
  })

  it('offers the deep link with its destination host when configured', () => {
    vi.stubEnv('VITE_SESSION_INSIGHT_URL', 'http://127.0.0.1:45615')
    render(
      <SessionInsightCard status={status({ state: 'connected', currentAttemptId: 'attempt_01JABC' })} />,
    )

    const link = screen.getByRole('link', { name: /Open current attempt in Session Insight/ })
    expect(link).toHaveAttribute(
      'href',
      'http://127.0.0.1:45615/#/session/worktree-review/attempt_01JABC',
    )
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(link.textContent).toContain('127.0.0.1:45615')
  })

  it('warns instead of guessing when connected but unconfigured', () => {
    render(
      <SessionInsightCard status={status({ state: 'connected', currentAttemptId: 'attempt_01JABC' })} />,
    )

    expect(screen.getByText(/address is not configured/)).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('states that observation never affects the gate', () => {
    render(<SessionInsightCard status={status({ state: 'disconnected' })} />)

    expect(
      screen.getByText(/Reviews still write a Session Journal for SI to read/),
    ).toBeInTheDocument()
  })
})
