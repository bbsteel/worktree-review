import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { useI18n } from '../i18n.tsx'
import { Button } from '../components/ui/button.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import { Tab, TabList, TabPanel, Tabs } from '../components/ui/tabs.tsx'
import { createReviewDataSource } from '../data/sources/create-review-data-source.ts'
import { ReviewNotFoundError, type ReviewDataSource } from '../data/sources/review-data-source.ts'
import {
  openReviewEventStream,
  type ReviewEventStreamState,
} from '../data/sources/review-events.ts'
import type { ReviewRunView } from '../domain/review.ts'
import {
  applyReviewEvent,
  isTerminalRunStatus,
} from '../features/review-detail/apply-review-event.ts'
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
  /** Injectable SSE factory for tests; production uses EventSource. */
  openEventStream?: typeof openReviewEventStream
}

/** Event types whose payloads change gate or terminal state; they trigger an authoritative refetch. */
const REFETCH_EVENT_TYPES = new Set(['stage.failed', 'gate.evaluated', 'attempt.completed'])

type LoadOutcome =
  | { status: 'not-found' }
  | { status: 'error' }
  | { status: 'loaded'; run: ReviewRunView }

interface LoadResult {
  attemptId: string
  outcome: LoadOutcome
}

export function ReviewDetailPage({ dataSource, openEventStream }: ReviewDetailPageProps) {
  const { t } = useI18n()
  const { attemptId } = useParams()
  const source = useMemo(() => dataSource ?? createReviewDataSource(), [dataSource])
  const openStream = openEventStream ?? openReviewEventStream
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = readTabParam(searchParams)
  const [result, setResult] = useState<LoadResult | null>(null)
  const [reloadIndex, setReloadIndex] = useState(0)
  const [streamState, setStreamState] = useState<ReviewEventStreamState | null>(null)
  const [streamEpoch, setStreamEpoch] = useState(0)
  const [lastSequence, setLastSequence] = useState(0)
  const lastSequenceRef = useRef(0)
  const streamAttemptRef = useRef<string | null>(null)

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

  const loadedRun =
    result !== null && result.attemptId === attemptId && result.outcome.status === 'loaded'
      ? result.outcome.run
      : null
  const runIsTerminal = loadedRun !== null && isTerminalRunStatus(loadedRun.runStatus)
  const hasLoadedRun = loadedRun !== null

  const refreshRun = useCallback(async () => {
    if (!attemptId) {
      return
    }
    try {
      const run = await source.getReviewRun(attemptId)
      setResult({ attemptId, outcome: { status: 'loaded', run } })
    } catch {
      // Keep the current view; stream state already reflects connectivity.
    }
  }, [source, attemptId])

  // Live updates: while the run is non-terminal, replay then follow its
  // ReviewEvents. Stage/dimension events update the view in place; gate and
  // terminal events refetch the authoritative run. Reconnects resume from
  // the last persisted sequence; duplicates are deduped by the stream.
  useEffect(() => {
    if (attemptId === undefined || !hasLoadedRun || runIsTerminal) {
      return
    }
    if (streamAttemptRef.current !== attemptId) {
      streamAttemptRef.current = attemptId
      lastSequenceRef.current = 0
    }

    let disposed = false
    const stream = openStream({
      attemptId,
      sinceSequence: lastSequenceRef.current,
      onEvent: (event) => {
        lastSequenceRef.current = Math.max(lastSequenceRef.current, event.sequence)
        setLastSequence(lastSequenceRef.current)
        setResult((current) => {
          if (current === null || current.outcome.status !== 'loaded') {
            return current
          }
          return {
            ...current,
            outcome: {
              status: 'loaded',
              run: applyReviewEvent(current.outcome.run, event).run,
            },
          }
        })
        if (REFETCH_EVENT_TYPES.has(event.event_type)) {
          void refreshRun()
        }
      },
      onStateChange: (state) => {
        if (!disposed) {
          setStreamState(state)
        }
      },
    })

    return () => {
      disposed = true
      stream.close()
    }
  }, [attemptId, hasLoadedRun, runIsTerminal, streamEpoch, openStream, refreshRun])

  const showLiveBanner =
    loadedRun !== null && !runIsTerminal && (streamState === 'reconnecting' || streamState === 'failed')
  const showLiveIndicator = loadedRun !== null && !runIsTerminal && streamState === 'live'

  if (!attemptId) {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <EmptyState
          title={t('Review attempt not found')}
          description={t('This link does not name a review attempt.')}
        />
      </main>
    )
  }

  if (result === null || result.attemptId !== attemptId) {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-40 w-full" label={t('Loading review header')} />
        <Skeleton className="mt-4 h-8 w-2/3" label={t('Loading review tabs')} />
        <Skeleton className="mt-4 h-64 w-full" label={t('Loading review content')} />
      </main>
    )
  }

  if (result.outcome.status === 'not-found') {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <EmptyState
          title={t('Review attempt not found')}
          description={`${t('No review attempt exists for "{attemptId}".', { attemptId })} ${t(
            'The link may be stale or the attempt belongs to another environment.',
          )}`}
        />
      </main>
    )
  }

  if (result.outcome.status === 'error') {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <EmptyState
          title={t('Could not load this review')}
          description={`${t('Loading attempt "{attemptId}" failed.', { attemptId })} ${t(
            'Retrying only reloads the same attempt — it never creates a new one.',
          )}`}
          action={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setResult(null)
                setReloadIndex((index) => index + 1)
              }}
            >
              {t('Retry loading')}
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

      {showLiveIndicator ? (
        <p role="status" className="mt-3 flex items-center gap-2 text-meta text-status-running">
          <span aria-hidden="true" className="inline-block h-2 w-2 animate-pulse rounded-full bg-status-running" />
          {t('Live updates connected — events replay from sequence {sequence}.', { sequence: lastSequence })}
        </p>
      ) : null}

      {showLiveBanner ? (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center gap-3 rounded-md border border-status-warning bg-surface px-3 py-2 text-sm text-text-primary"
        >
          {streamState === 'reconnecting' ? (
            <span>
              {t(
                'Live connection lost — reconnecting from the last received event (sequence {sequence}). The review keeps running on the server.',
                { sequence: lastSequence },
              )}
            </span>
          ) : (
            <>
              <span>
                {t(
                  'Live updates disconnected. The review keeps running on the server; refresh or reconnect to follow it again.',
                )}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setStreamEpoch((epoch) => epoch + 1)
                }}
              >
                {t('Reconnect live updates')}
              </Button>
            </>
          )}
        </div>
      ) : null}

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
        <TabList aria-label={t('Review detail sections')} className="overflow-x-auto">
          {REVIEW_DETAIL_TABS.map((tab) => (
            <Tab key={tab} value={tab}>
              {t(REVIEW_DETAIL_TAB_LABEL[tab])}
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
        {t('Attempt')} <CopyValue value={run.attemptId} label={t('Attempt ID')} truncate={false} /> ·{' '}
        {run.summary.repositoryDisplayName}
      </footer>
    </main>
  )
}
