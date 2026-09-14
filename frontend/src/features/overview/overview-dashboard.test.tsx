import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApplicationShell } from '../../components/application-shell/ApplicationShell.tsx'
import { BLOCKED_DEMO_ATTEMPT_ID } from '../../data/index.ts'
import { DataSourceProvider } from '../../app/DataSourceProvider.tsx'
import { ThemeProvider } from '../../app/ThemeProvider.tsx'
import { OverviewPage } from '../../pages/OverviewPage.tsx'
import { stubMatchMedia } from '../../test/match-media.ts'

beforeEach(() => {
  // Dashboard tests render the offline demo fixtures.
  vi.stubEnv('VITE_REVIEW_DATA_SOURCE', 'mock')
})

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function renderOverview(path = '/overview') {
  stubMatchMedia({
    '(prefers-color-scheme: light)': false,
    '(prefers-reduced-motion: reduce)': false,
  })
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <ThemeProvider>
            <DataSourceProvider>
              <ApplicationShell />
            </DataSourceProvider>
          </ThemeProvider>
        ),
        children: [{ path: 'overview', element: <OverviewPage /> }],
      },
    ],
    { initialEntries: [path] },
  )
  return render(<RouterProvider router={router} />)
}

describe('Overview dashboard', () => {
  it('places needs-attention before statistics', async () => {
    renderOverview()
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Needs attention/ })).toBeInTheDocument()
    })
    const headings = screen.getAllByRole('heading').map((node) => node.textContent ?? '')
    expect(headings.indexOf('Overview')).toBeLessThan(
      headings.findIndex((text) => text.startsWith('Needs attention')),
    )
    expect(headings.findIndex((text) => text.startsWith('Needs attention'))).toBeLessThan(
      headings.indexOf('Statistics'),
    )
  })

  it('explains Gate pass-rate denominator and unknown cost', async () => {
    renderOverview()
    await waitFor(() => {
      expect(screen.getByText(/Gate pass rate is Passed \/ \(Passed \+ Blocked\)/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Unknown cost is counted separately/)).toBeInTheDocument()
    expect(screen.getByText(/1 unknown/)).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('links the blocked attention item to its attempt', async () => {
    renderOverview()
    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: 'acme/payment-service' }).length).toBeGreaterThan(0)
    })
    expect(screen.getAllByRole('link', { name: 'acme/payment-service' })[0]).toHaveAttribute(
      'href',
      `/reviews/${BLOCKED_DEMO_ATTEMPT_ID}`,
    )
  })

  it('filters lists by repository query without dropping the action-first order', async () => {
    const user = userEvent.setup()
    renderOverview()
    await waitFor(() => {
      expect(screen.getByLabelText('Repository')).toBeInTheDocument()
    })
    await user.selectOptions(screen.getByLabelText('Repository'), 'acme/session-insight')
    expect(screen.queryByRole('link', { name: 'acme/payment-service' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'acme/session-insight' })).toBeInTheDocument()
  })
})
