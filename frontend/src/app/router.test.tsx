import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OverviewPage } from '../pages/OverviewPage.tsx'
import { ApplicationShell } from '../components/application-shell/ApplicationShell.tsx'
import { DataSourceProvider } from './DataSourceProvider.tsx'
import { ReviewDetailRoute } from './ReviewDetailRoute.tsx'
import { ThemeProvider } from './ThemeProvider.tsx'
import { stubMatchMedia } from '../test/match-media.ts'

beforeEach(() => {
  // These route tests exercise the offline demo fixture routes.
  vi.stubEnv('VITE_REVIEW_DATA_SOURCE', 'mock')
})

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function renderPath(path: string) {
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
        children: [
          { path: 'overview', element: <OverviewPage /> },
          { path: 'reviews/:attemptId', element: <ReviewDetailRoute /> },
        ],
      },
    ],
    { initialEntries: [path] },
  )
  return render(<RouterProvider router={router} />)
}

describe('assembled routes', () => {
  it('renders the Overview dashboard', async () => {
    renderPath('/overview')
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    })
  })

  it('renders the real Review Detail page for a fixture attempt id', async () => {
    renderPath('/reviews/attempt_01JY8R7F2W')
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'acme/payment-service · PR #184' }),
      ).toBeInTheDocument()
    })
  })

  it('shows the unified Mock/Pre-Alpha badge and demo case selector on every route', async () => {
    renderPath('/reviews/attempt_01JY8R7F2W')
    await waitFor(() => {
      expect(screen.getByTestId('prototype-badge')).toHaveTextContent('Mock data · Pre-Alpha')
    })
    expect(screen.getByRole('combobox', { name: 'Demo case' })).toBeInTheDocument()
  })
})
