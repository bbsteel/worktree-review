import { createBrowserRouter, Navigate } from 'react-router'
import { ApplicationShell } from '../components/application-shell/ApplicationShell.tsx'
import { AuditLogPage } from '../pages/AuditLogPage.tsx'
import { NewReviewPage } from '../pages/NewReviewPage.tsx'
import { OverviewPage } from '../pages/OverviewPage.tsx'
import { PoliciesPage } from '../pages/PoliciesPage.tsx'
import { PolicyEditorPage } from '../pages/PolicyEditorPage.tsx'
import { ProvidersPage } from '../pages/ProvidersPage.tsx'
import { RepositoriesPage } from '../pages/RepositoriesPage.tsx'
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
      { path: 'reviews/new', element: <NewReviewPage /> },
      { path: 'reviews/:attemptId', element: <ReviewDetailRoute /> },
      { path: 'repositories', element: <RepositoriesPage /> },
      { path: 'providers', element: <ProvidersPage /> },
      { path: 'policies', element: <PoliciesPage /> },
      {
        path: 'policies/review/:policyId/edit',
        element: <PolicyEditorPage kind="review" />,
      },
      {
        path: 'policies/compute/:policyId/edit',
        element: <PolicyEditorPage kind="compute" />,
      },
      { path: 'audit', element: <AuditLogPage /> },
    ],
  },
])
