import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { Badge } from '../components/ui/badge.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import { Tab, TabList, TabPanel, Tabs } from '../components/ui/tabs.tsx'
import { createReviewDataSource } from '../data/sources/create-review-data-source.ts'
import { ReviewNotFoundError, type ReviewDataSource } from '../data/sources/review-data-source.ts'
import type { ReviewRunView } from '../domain/review.ts'
import { CopyValue } from '../features/review-detail/CopyValue.tsx'
import {
  REVIEW_DETAIL_TAB_LABEL,
  REVIEW_DETAIL_TABS,
  readTabParam,
  withTabParam,
} from '../features/review-detail/review-tabs.ts'
import { ReviewHeader } from '../features/review-detail/ReviewHeader.tsx'

interface ReviewDetailPageProps {
  /** Injectable for tests; the app uses the configured default source. */
  dataSource?: ReviewDataSource
}

type LoadOutcome =
  | { status: 'not-found' }
  | { status: 'error' }
  | { status: 'loaded'; run: ReviewRunView }

interface LoadResult {
  attemptId: string
  outcome: LoadOutcome
}

export function ReviewDetailPage({ dataSource }: ReviewDetailPageProps) {
  const { attemptId } = useParams()
  const source = useMemo(() => dataSource ?? createReviewDataSource(), [dataSource])
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = readTabParam(searchParams)
  const [result, setResult] = useState<LoadResult | null>(null)

  useEffect(() => {
    if (!attemptId) {
      return
    }

    let cancelled = false

    source
      .getReviewRun(attemptId)
      .then((run) => {
        if (!cancelled) {
          setResult({ attemptId, outcome: { status: 'loaded', run } })
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        setResult({
          attemptId,
          outcome:
            error instanceof ReviewNotFoundError ? { status: 'not-found' } : { status: 'error' },
        })
      })

    return () => {
      cancelled = true
    }
  }, [source, attemptId])

  if (!attemptId) {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <EmptyState
          title="Review attempt not found"
          description="This link does not name a review attempt."
        />
      </main>
    )
  }

  if (result === null || result.attemptId !== attemptId) {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-40 w-full" label="Loading review header" />
        <Skeleton className="mt-4 h-8 w-2/3" label="Loading review tabs" />
        <Skeleton className="mt-4 h-64 w-full" label="Loading review content" />
      </main>
    )
  }

  if (result.outcome.status === 'not-found') {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <EmptyState
          title="Review attempt not found"
          description={`No review attempt exists for "${attemptId}". The link may be stale or the attempt belongs to another environment.`}
        />
      </main>
    )
  }

  if (result.outcome.status === 'error') {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <EmptyState
          title="Could not load this review"
          description={`Loading attempt "${attemptId}" failed. No new attempt was created; reload the page to try again.`}
        />
      </main>
    )
  }

  const { run } = result.outcome

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-6">
      {source.environmentBadge !== null ? (
        <div className="mb-3 flex items-center gap-2">
          <Badge tone="warning" label={source.environmentBadge} />
          <span className="text-meta text-text-secondary">
            Prototype data for interaction review; not a live pipeline result.
          </span>
        </div>
      ) : null}

      <ReviewHeader run={run} />

      <Tabs
        value={activeTab}
        onValueChange={(tab) => {
          if (tab !== activeTab && (REVIEW_DETAIL_TABS as readonly string[]).includes(tab)) {
            setSearchParams(withTabParam(searchParams, tab as (typeof REVIEW_DETAIL_TABS)[number]))
          }
        }}
        className="mt-4"
      >
        <TabList aria-label="Review detail sections" className="overflow-x-auto">
          {REVIEW_DETAIL_TABS.map((tab) => (
            <Tab key={tab} value={tab}>
              {REVIEW_DETAIL_TAB_LABEL[tab]}
            </Tab>
          ))}
        </TabList>

        <TabPanel value="overview">
          <p className="text-sm text-text-secondary">
            Overview content (gate summaries, dimensions, pipeline) is delivered in B-011.
          </p>
        </TabPanel>
        <TabPanel value="findings">
          <p className="text-sm text-text-secondary">
            Findings workspace ({run.findings.length} findings) is delivered in B-012.
          </p>
        </TabPanel>
        <TabPanel value="coverage">
          <p className="text-sm text-text-secondary">Coverage detail is delivered in B-013.</p>
        </TabPanel>
        <TabPanel value="attempts">
          <p className="text-sm text-text-secondary">Attempt timeline is delivered in B-013.</p>
        </TabPanel>
        <TabPanel value="identity">
          <p className="text-sm text-text-secondary">Identity and provenance are delivered in B-013.</p>
        </TabPanel>
        <TabPanel value="policies">
          <p className="text-sm text-text-secondary">Policy snapshots are delivered in B-013.</p>
        </TabPanel>
        <TabPanel value="usage">
          <p className="text-sm text-text-secondary">Usage detail is delivered in B-013.</p>
        </TabPanel>
      </Tabs>

      <footer className="mt-6 border-t border-border pt-3 text-meta text-text-secondary">
        Attempt <CopyValue value={run.attemptId} label="Attempt ID" truncate={false} /> ·{' '}
        {run.summary.repositoryDisplayName}
      </footer>
    </main>
  )
}
