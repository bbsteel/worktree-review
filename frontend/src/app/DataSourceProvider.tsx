import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createReviewDataSource } from '../data/index.ts'
import type { FixtureCaseDescriptor, OverviewView } from '../domain/overview.ts'
import { DataSourceContext } from './data-source.ts'

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const source = useMemo(() => createReviewDataSource(), [])
  const [overview, setOverview] = useState<OverviewView | null>(null)
  const [cases, setCases] = useState<FixtureCaseDescriptor[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([source.getOverview(), source.listCases()])
      .then(([nextOverview, nextCases]) => {
        if (cancelled) {
          return
        }
        setOverview(nextOverview)
        setCases(nextCases)
        setError(null)
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return
        }
        setError(caught instanceof Error ? caught.message : 'Failed to load review data')
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [source])

  const value = useMemo(
    () => ({ source, overview, cases, loading, error }),
    [source, overview, cases, loading, error],
  )

  return <DataSourceContext.Provider value={value}>{children}</DataSourceContext.Provider>
}
