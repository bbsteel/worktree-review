import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { MockReviewDataSource } from '../data/sources/mock-review-data-source.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { ReviewDetailPage } from './ReviewDetailPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

function renderPage(path: string): ReturnType<typeof createMemoryRouter> {
  const router = createMemoryRouter(
    [{ path: '/reviews/:attemptId', element: <ReviewDetailPage dataSource={new MockReviewDataSource()} /> }],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('ReviewDetailPage', () => {
  it('loads the blocked fixture and renders the header with the mock badge', async () => {
    renderPage('/reviews/attempt_01JY8R7F2W')

    expect(
      await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Mock data · Pre-Alpha')).toBeInTheDocument()
    expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0)
  })

  it('renders all seven detail tabs', async () => {
    renderPage('/reviews/attempt_01JY8R7F2W')
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })

    for (const label of [
      'Overview',
      'Findings',
      'Coverage',
      'Attempts',
      'Identity & Provenance',
      'Policies',
      'Usage',
    ]) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument()
    }
  })

  it('switches tabs and persists the tab in the URL', async () => {
    const user = userEvent.setup()
    const router = renderPage('/reviews/attempt_01JY8R7F2W')
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })

    await user.click(screen.getByRole('tab', { name: 'Findings' }))

    expect(router.state.location.search).toContain('tab=findings')
    expect(screen.getByRole('tab', { name: 'Findings' })).toHaveAttribute('aria-selected', 'true')
  })

  it('restores the active tab from a direct link', async () => {
    renderPage('/reviews/attempt_01JY8R7F2W?tab=coverage')

    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })
    expect(screen.getByRole('tab', { name: 'Coverage' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Coverage detail is delivered in B-013.')
  })

  it('supports arrow-key tab navigation', async () => {
    const user = userEvent.setup()
    renderPage('/reviews/attempt_01JY8R7F2W')
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })

    const overviewTab = screen.getByRole('tab', { name: 'Overview' })
    overviewTab.focus()
    await user.keyboard('{ArrowRight}')

    expect(screen.getByRole('tab', { name: 'Findings' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Findings' })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows a not-found state for unknown attempts without creating anything', async () => {
    renderPage('/reviews/attempt_does_not_exist')

    expect(await screen.findByText('Review attempt not found')).toBeInTheDocument()
    expect(screen.getByText(/attempt_does_not_exist/)).toBeInTheDocument()
  })

  it('renders the local passed fixture without GitHub-only fields', async () => {
    renderPage('/reviews/attempt_01JY8P4SS0D')

    expect(
      await screen.findByRole('heading', { name: 'acme/session-insight' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('Passed').length).toBeGreaterThan(0)
    expect(screen.queryByText(/^Author$/)).not.toBeInTheDocument()
  })
})
