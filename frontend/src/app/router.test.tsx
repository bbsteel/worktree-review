import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { OverviewPage } from '../pages/OverviewPage.tsx'
import { ReviewDetailPlaceholder } from './ReviewDetailPlaceholder.tsx'

function renderPath(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/', element: <OverviewPage /> },
      { path: '/overview', element: <OverviewPage /> },
      { path: '/reviews/:attemptId', element: <ReviewDetailPlaceholder /> },
    ],
    { initialEntries: [path] },
  )

  return render(<RouterProvider router={router} />)
}

describe('empty routes', () => {
  it('renders the Overview empty page', () => {
    renderPath('/overview')
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('renders the Review Detail empty page for an attempt id', () => {
    renderPath('/reviews/attempt_01JY8R7F2W')
    expect(screen.getByRole('heading', { name: 'Review Detail' })).toBeInTheDocument()
    expect(screen.getByTestId('attempt-id')).toHaveTextContent('attempt_01JY8R7F2W')
  })
})
