import { createBrowserRouter, Navigate } from 'react-router'
import { OverviewPage } from '../pages/OverviewPage.tsx'
import { ReviewDetailPlaceholder } from './ReviewDetailPlaceholder.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/overview" replace />,
  },
  {
    path: '/overview',
    element: <OverviewPage />,
  },
  {
    path: '/reviews/:attemptId',
    element: <ReviewDetailPlaceholder />,
  },
])
