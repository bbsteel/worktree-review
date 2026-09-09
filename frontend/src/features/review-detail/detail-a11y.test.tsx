/**
 * Keyboard and focus accessibility for Review Detail (design 21.2, B-015).
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { blockedCase } from '../../data/fixtures/index.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { FindingsTab } from './FindingsTab.tsx'
import { ReviewHeader } from './ReviewHeader.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

describe('keyboard operation', () => {
  it('selects a finding with the keyboard only', async () => {
    const user = userEvent.setup()
    const router = createMemoryRouter(
      [{ path: '/reviews/:attemptId', element: <FindingsTab run={blockedCase} /> }],
      { initialEntries: [`/reviews/${blockedCase.attemptId}?tab=findings`] },
    )
    render(<RouterProvider router={router} />)

    const list = screen.getByRole('list', { name: 'Findings' })
    const button = within(list)
      .getByText(/Retention disclosure is duplicated/)
      .closest('button')
    expect(button).not.toBeNull()
    button?.focus()
    expect(button).toHaveFocus()
    // jsdom does not implement the Enter-on-button click default action;
    // dispatch the keydown and its browser default click like a real browser.
    fireEvent.keyDown(button as HTMLButtonElement, { key: 'Enter' })
    fireEvent.click(button as HTMLButtonElement)

    expect(
      screen.getByRole('heading', { name: /Retention disclosure is duplicated/ }),
    ).toBeInTheDocument()
    expect(router.state.location.search).toContain('finding=fp_4c81de70_retention_disclosure_dup')
    expect(user).toBeDefined()
  })

  it('operates the blocking-only filter with the keyboard', async () => {
    const user = userEvent.setup()
    const router = createMemoryRouter(
      [{ path: '/reviews/:attemptId', element: <FindingsTab run={blockedCase} /> }],
      { initialEntries: [`/reviews/${blockedCase.attemptId}?tab=findings`] },
    )
    render(<RouterProvider router={router} />)

    const checkbox = screen.getByRole('checkbox', { name: 'Blocking only' })
    checkbox.focus()
    await user.keyboard('[Space]')

    expect(checkbox).toBeChecked()
    expect(screen.getByText('1 of 3 findings')).toBeInTheDocument()
  })
})

describe('tooltip accessibility', () => {
  it('reveals the disabled reason on keyboard focus', () => {
    render(<ReviewHeader run={blockedCase} />)

    const bypassWrapper = screen.getByLabelText(/Bypass unavailable:/)
    // Browsers fire focusin on keyboard focus; jsdom focus() does not, so
    // dispatch focusin directly.
    fireEvent.focusIn(bypassWrapper)

    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'Bypass means accepting the risk. It does not mean the finding was resolved.',
    )
  })
})
