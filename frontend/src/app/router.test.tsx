import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { OverviewPage } from '../pages/OverviewPage.tsx'
import { ApplicationShell } from '../components/application-shell/ApplicationShell.tsx'
import { DataSourceProvider } from './DataSourceProvider.tsx'
import { ReviewDetailPlaceholder } from './ReviewDetailPlaceholder.tsx'
import { ThemeProvider } from './ThemeProvider.tsx'
import { stubMatchMedia } from '../test/match-media.ts'

afterEach(() => {
  cleanup()
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
          { path: 'reviews/:attemptId', element: <ReviewDetailPlaceholder /> },
        ],
      },
    ],
    { initialEntries: [path] },
  )
  return render(<RouterProvider router={router} />)
}

describe('empty routes', () => {
  it('renders the Overview empty page', async () => {
    renderPath('/overview')
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    })
  })

  it('renders the Review Detail empty page for an attempt id', async () => {
    renderPath('/reviews/attempt_01JY8R7F2W')
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Review Detail' })).toBeInTheDocument()
    })
    expect(screen.getByTestId('attempt-id')).toHaveTextContent('attempt_01JY8R7F2W')
  })
})
