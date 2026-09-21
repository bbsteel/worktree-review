import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { blockedCase } from '../../data/fixtures/index.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { ReviewActionsBar } from './ReviewActionsBar.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function withSessionInsight(enabled: boolean) {
  const run = structuredClone(blockedCase)
  run.availableActions.openSessionInsight = {
    visible: true,
    enabled,
    disabledReason: enabled ? null : 'Session Insight is not connected.',
  }
  return run
}

describe('ReviewActionsBar Session Insight deep link', () => {
  it('renders a real link with destination host when enabled and configured', () => {
    vi.stubEnv('VITE_SESSION_INSIGHT_URL', 'http://127.0.0.1:45615')
    render(<ReviewActionsBar run={withSessionInsight(true)} />)

    const link = screen.getByRole('link', { name: /Open Session Insight/ })
    expect(link).toHaveAttribute(
      'href',
      'http://127.0.0.1:45615/#/session/worktree-review/attempt_01JY8R7F2W',
    )
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(link.textContent).toContain('127.0.0.1:45615')
  })

  it('stays disabled with a reason when enabled but no address is configured', () => {
    render(<ReviewActionsBar run={withSessionInsight(true)} />)

    expect(screen.queryByRole('link', { name: /Open Session Insight/ })).not.toBeInTheDocument()
    expect(
      screen.getByLabelText(/Open Session Insight unavailable: Session Insight address is not configured/),
    ).toBeInTheDocument()
  })

  it('keeps the backend disabled reason when the capability is off', () => {
    vi.stubEnv('VITE_SESSION_INSIGHT_URL', 'http://127.0.0.1:45615')
    render(<ReviewActionsBar run={withSessionInsight(false)} />)

    expect(screen.queryByRole('link', { name: /Open Session Insight/ })).not.toBeInTheDocument()
    expect(
      screen.getByLabelText(/Open Session Insight unavailable: Session Insight is not connected/),
    ).toBeInTheDocument()
  })
})
