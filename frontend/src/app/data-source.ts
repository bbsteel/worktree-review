import { createContext, useContext } from 'react'
import type { ReviewDataSource } from '../data/sources/review-data-source.ts'
import type { AuthSessionView } from '../domain/audit.ts'
import type { FixtureCaseDescriptor, OverviewView } from '../domain/overview.ts'

export interface DataSourceContextValue {
  source: ReviewDataSource
  overview: OverviewView | null
  cases: FixtureCaseDescriptor[]
  loading: boolean
  error: string | null
  /**
   * Deployment auth session (P3). `null` until probed; in the authorized
   * mode an unauthenticated session means the shell shows a sign-in wall and
   * no protected data is ever fetched.
   */
  authSession: AuthSessionView | null
}

export const DataSourceContext = createContext<DataSourceContextValue | null>(null)

export function useDataSource(): DataSourceContextValue {
  const value = useContext(DataSourceContext)
  if (!value) {
    throw new Error('useDataSource must be used within DataSourceProvider')
  }
  return value
}
