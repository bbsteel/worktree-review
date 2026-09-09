import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { blockedCase, passedCase } from '../../data/fixtures/index.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { FindingsTab } from './FindingsTab.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

function renderTab(run: ReviewRunView, initialQuery = '') {
  const router = createMemoryRouter(
    [{ path: '/reviews/:attemptId', element: <FindingsTab run={run} /> }],
    { initialEntries: [`/reviews/${run.attemptId}${initialQuery}`] },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('FindingsTab master list', () => {
  it('lists all three blocked-case findings with severity text badges', () => {
    renderTab(blockedCase)

    const list = screen.getByRole('list', { name: 'Findings' })
    expect(within(list).getAllByRole('button')).toHaveLength(3)
    expect(within(list).getByText('Major')).toBeInTheDocument()
    expect(within(list).getByText('Minor')).toBeInTheDocument()
    expect(within(list).getByText('Suggestion')).toBeInTheDocument()
    expect(screen.getByText('3 of 3 findings')).toBeInTheDocument()
  })

  it('filters to blocking findings only', async () => {
    const user = userEvent.setup()
    renderTab(blockedCase)

    await user.click(screen.getByRole('checkbox', { name: 'Blocking only' }))

    const list = screen.getByRole('list', { name: 'Findings' })
    expect(within(list).getAllByRole('button')).toHaveLength(1)
    expect(screen.getByText('1 of 3 findings')).toBeInTheDocument()
  })

  it('filters by severity via the select', async () => {
    const user = userEvent.setup()
    renderTab(blockedCase)

    await user.selectOptions(screen.getByRole('combobox', { name: 'Severity' }), 'minor')

    const list = screen.getByRole('list', { name: 'Findings' })
    expect(within(list).getAllByRole('button')).toHaveLength(1)
    expect(within(list).getByText(/Retention disclosure is duplicated/)).toBeInTheDocument()
  })

  it('searches across problem, path and fingerprint', async () => {
    const user = userEvent.setup()
    renderTab(blockedCase)

    await user.type(
      screen.getByRole('searchbox', { name: /Search problem, path, or fingerprint/ }),
      'app.py',
    )

    const list = screen.getByRole('list', { name: 'Findings' })
    expect(within(list).getAllByRole('button')).toHaveLength(1)
    expect(within(list).getByText(/GitHub transport mapping/)).toBeInTheDocument()
  })

  it('shows an empty-filter result without touching the gate', async () => {
    const user = userEvent.setup()
    renderTab(blockedCase)

    await user.type(
      screen.getByRole('searchbox', { name: /Search problem, path, or fingerprint/ }),
      'nothing-matches-this',
    )

    expect(screen.getByText('No findings match the filters')).toBeInTheDocument()
    expect(screen.getByText(/The gate result is unchanged/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument()
  })

  it('restores filters from the URL query', () => {
    renderTab(blockedCase, '?tab=findings&severity=suggestion&blocking=1')

    // blocking + suggestion is an impossible combination for the fixtures
    expect(screen.getByText('No findings match the filters')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Severity' })).toHaveValue('suggestion')
    expect(screen.getByRole('checkbox', { name: 'Blocking only' })).toBeChecked()
  })
})

describe('FindingsTab detail pane', () => {
  it('shows the first finding by default with evidence and line numbers', () => {
    renderTab(blockedCase)

    expect(
      screen.getByRole('heading', {
        name: /fallback branch still accepts the webhook request/,
      }),
    ).toBeInTheDocument()

    const figure = screen.getByText(/verified quoted source/).closest('figure')
    expect(figure?.textContent).toContain('if header is None:')
    expect(figure?.textContent).toContain('signature header missing; accepting for compatibility')
    expect(figure?.textContent).toContain('74')
    expect(screen.getByText(/review-worktree/)).toBeInTheDocument()
    expect(screen.getAllByText('fp_9f3c1a2b').length).toBeGreaterThan(0)
  })

  it('switches detail when another finding is selected and syncs the URL', async () => {
    const user = userEvent.setup()
    const router = renderTab(blockedCase)

    const list = screen.getByRole('list', { name: 'Findings' })
    await user.click(within(list).getByText(/Retention disclosure is duplicated/))

    expect(
      screen.getByRole('heading', { name: /Retention disclosure is duplicated/ }),
    ).toBeInTheDocument()
    const figure = screen.getByText(/verified quoted source/).closest('figure')
    expect(figure?.textContent).toContain('duplicated below for local-cli adapter')
    expect(router.state.location.search).toContain('finding=fp_4c81de70_retention_disclosure_dup')
  })

  it('restores the selected finding from a direct link', () => {
    renderTab(blockedCase, '?tab=findings&finding=fp_b2a90e11_github_transport_mapping')

    expect(
      screen.getByRole('heading', { name: /GitHub transport mapping/ }),
    ).toBeInTheDocument()
  })

  it('never offers automatic fix, commit or push actions', () => {
    renderTab(blockedCase)

    expect(screen.queryByRole('button', { name: /apply fix/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /commit/i })).not.toBeInTheDocument()
    expect(screen.getByText(/never modifies, commits or pushes/)).toBeInTheDocument()
  })

  it('shows an honest empty state for a passed run with zero findings', () => {
    renderTab(passedCase)

    expect(screen.getByText('No findings')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Findings' })).not.toBeInTheDocument()
  })
})
