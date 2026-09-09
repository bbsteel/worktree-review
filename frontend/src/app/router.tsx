import { createBrowserRouter, Navigate } from 'react-router'
import { ApplicationShell } from '../components/application-shell/ApplicationShell.tsx'
import { OverviewPage } from '../pages/OverviewPage.tsx'
import { DataSourceProvider } from './DataSourceProvider.tsx'
import { ReviewDetailRoute } from './ReviewDetailRoute.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <DataSourceProvider>
        <ApplicationShell />
      </DataSourceProvider>
    ),
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: 'overview', element: <OverviewPage /> },
      { path: 'reviews/:attemptId', element: <ReviewDetailRoute /> },
    ],
  },
])
