import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { MOCK_DATA_BADGE } from '../../data/index.ts'
import { OverviewPage } from '../../pages/OverviewPage.tsx'
import { DataSourceProvider } from '../../app/DataSourceProvider.tsx'
import { ReviewDetailRoute } from '../../app/ReviewDetailRoute.tsx'
import { ThemeProvider } from '../../app/ThemeProvider.tsx'
import { stubMatchMedia } from '../../test/match-media.ts'
import { ApplicationShell } from './ApplicationShell.tsx'

afterEach(() => {
  cleanup()
})

function renderShell(path = '/overview') {
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

describe('ApplicationShell', () => {
  it('shows the prototype badge and hides search', async () => {
    renderShell()
    await waitFor(() => {
      expect(screen.getByTestId('prototype-badge')).toHaveTextContent(MOCK_DATA_BADGE)
    })
    expect(screen.queryByRole('search')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/search/i)).not.toBeInTheDocument()
  })

  it('links implemented pages and marks the rest as Preview with reasons', async () => {
    renderShell()
    await waitFor(() => {
      expect(screen.getByRole('link', { name: /New Review/ })).toHaveAttribute(
        'href',
        '/reviews/new',
      )
    })
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/overview')
    expect(screen.getByRole('link', { name: 'Repositories' })).toHaveAttribute(
      'href',
      '/repositories',
    )
    expect(screen.getByRole('link', { name: 'Policies' })).toHaveAttribute('href', '/policies')
    expect(screen.getByRole('link', { name: 'Providers' })).toHaveAttribute('href', '/providers')
    expect(screen.getByRole('button', { name: /Reviews/ })).toHaveAccessibleDescription(
      /Reviews list is Preview/,
    )
    expect(screen.getByRole('button', { name: /Session Insight/ })).toHaveAccessibleDescription(
      /Session Insight is disconnected/,
    )
  })

  it('opens narrow navigation from the menu button', async () => {
    const user = userEvent.setup()
    renderShell()
    await waitFor(() => {
      expect(screen.getByLabelText('Open navigation')).toBeInTheDocument()
    })
    await user.click(screen.getByLabelText('Open navigation'))
    expect(screen.getByLabelText('Close navigation')).toBeInTheDocument()
  })

  it('keeps Overview and Review Detail routes reachable inside the shell', async () => {
    renderShell('/reviews/attempt_01JY8R7F2W')
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'acme/payment-service · PR #184' }),
      ).toBeInTheDocument()
    })
    expect(screen.getByTestId('prototype-badge')).toHaveTextContent(MOCK_DATA_BADGE)
  })
})
