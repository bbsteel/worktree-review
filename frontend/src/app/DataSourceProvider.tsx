import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createReviewDataSource } from '../data/index.ts'
import type { AuthSessionView } from '../domain/audit.ts'
import type { FixtureCaseDescriptor, OverviewView } from '../domain/overview.ts'
import { DataSourceContext } from './data-source.ts'

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const source = useMemo(() => createReviewDataSource(), [])
  const [authSession, setAuthSession] = useState<AuthSessionView | null>(null)
  const [overview, setOverview] = useState<OverviewView | null>(null)
  const [cases, setCases] = useState<FixtureCaseDescriptor[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    // Auth first (P3): in the authorized deployment an unauthenticated user
    // gets the sign-in wall and NO protected data is ever requested. The
    // session probe itself is exempt on the server.
    const sessionProbe: Promise<AuthSessionView | null> =
      source.getAuthSession === undefined
        ? Promise.resolve(null)
        : source.getAuthSession().catch(() => null)

    sessionProbe
      .then((session) => {
        if (cancelled) {
          return
        }
        setAuthSession(session)
        if (session !== null && session.mode === 'github-oauth' && !session.authenticated) {
          setOverview(null)
          setCases([])
          setError(null)
          setLoading(false)
          return
        }
        return Promise.all([source.getOverview(), source.listCases()]).then(
          ([nextOverview, nextCases]) => {
            if (cancelled) {
              return
            }
            setOverview(nextOverview)
            setCases(nextCases)
            setError(null)
          },
        )
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
    () => ({ source, overview, cases, loading, error, authSession }),
    [source, overview, cases, loading, error, authSession],
  )

  return <DataSourceContext.Provider value={value}>{children}</DataSourceContext.Provider>
}
