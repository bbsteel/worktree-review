import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { Button } from '../components/ui/button.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import { Tab, TabList, TabPanel, Tabs } from '../components/ui/tabs.tsx'
import { createReviewDataSource } from '../data/sources/create-review-data-source.ts'
import { ReviewNotFoundError, type ReviewDataSource } from '../data/sources/review-data-source.ts'
import type { ReviewRunView } from '../domain/review.ts'
import { CopyValue } from '../features/review-detail/CopyValue.tsx'
import { AttemptsTab } from '../features/review-detail/AttemptsTab.tsx'
import { CoverageTab } from '../features/review-detail/CoverageTab.tsx'
import { FindingsTab } from '../features/review-detail/FindingsTab.tsx'
import { IdentityTab } from '../features/review-detail/IdentityTab.tsx'
import { PoliciesTab } from '../features/review-detail/PoliciesTab.tsx'
import { UsageTab } from '../features/review-detail/UsageTab.tsx'
import { MergeCandidatePath } from '../features/review-detail/MergeCandidatePath.tsx'
import { OverviewTab } from '../features/review-detail/OverviewTab.tsx'
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
  const [reloadIndex, setReloadIndex] = useState(0)

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
  }, [source, attemptId, reloadIndex])

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
          description={`Loading attempt "${attemptId}" failed. Retrying only reloads the same attempt — it never creates a new one.`}
          action={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setResult(null)
                setReloadIndex((index) => index + 1)
              }}
            >
              Retry loading
            </Button>
          }
        />
      </main>
    )
  }

  const { run } = result.outcome

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-6">
      {/* PM-010: the single Mock/Pre-Alpha environment indicator lives in the
          ApplicationShell banner; per-case provenance (handwritten mock vs
          real pipeline snapshot) is shown by the banner's demo case selector,
          so this page does not repeat a source-level badge here. */}
      <ReviewHeader run={run} />

      <div className="mt-4">
        <MergeCandidatePath run={run} />
      </div>

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
          <OverviewTab run={run} />
        </TabPanel>
        <TabPanel value="findings">
          <FindingsTab run={run} />
        </TabPanel>
        <TabPanel value="coverage">
          <CoverageTab run={run} />
        </TabPanel>
        <TabPanel value="attempts">
          <AttemptsTab run={run} />
        </TabPanel>
        <TabPanel value="identity">
          <IdentityTab run={run} />
        </TabPanel>
        <TabPanel value="policies">
          <PoliciesTab run={run} />
        </TabPanel>
        <TabPanel value="usage">
          <UsageTab run={run} />
        </TabPanel>
      </Tabs>

      <footer className="mt-6 border-t border-border pt-3 text-meta text-text-secondary">
        Attempt <CopyValue value={run.attemptId} label="Attempt ID" truncate={false} /> ·{' '}
        {run.summary.repositoryDisplayName}
      </footer>
    </main>
  )
}
