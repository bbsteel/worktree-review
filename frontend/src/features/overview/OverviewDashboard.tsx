import { Link, useSearchParams } from 'react-router'
import { useDataSource } from '../../app/data-source.ts'
import { Badge } from '../../components/ui/badge.tsx'
import { EmptyState } from '../../components/ui/empty-state.tsx'
import { Skeleton } from '../../components/ui/skeleton.tsx'
import { OverviewCharts } from './OverviewCharts.tsx'
import { filterOverviewLists, type SurfaceFilter } from './filter.ts'
import { formatCost, formatDuration, gateBadge } from './format.ts'
import { ReviewSummaryCard } from './ReviewSummaryCard.tsx'
import { SessionInsightCard } from './SessionInsightCard.tsx'
import { StatsStrip } from './StatsStrip.tsx'

export function OverviewDashboard() {
  const { overview, loading, error } = useDataSource()
  const [searchParams, setSearchParams] = useSearchParams()
  const repository = searchParams.get('repository')
  const surface = (searchParams.get('surface') as SurfaceFilter | null) ?? 'all'

  if (loading || !overview) {
    return (
      <main className="p-4 md:p-6">
        <h1 className="text-xl font-semibold">Overview</h1>
        <Skeleton className="mt-4 h-24 w-full" label="Loading overview" />
      </main>
    )
  }

  if (error) {
    return (
      <main className="p-4 md:p-6">
        <h1 className="text-xl font-semibold">Overview</h1>
        <EmptyState title="Overview unavailable" description={error} />
      </main>
    )
  }

  const lists = filterOverviewLists(overview, repository, surface)

  function setSurface(next: SurfaceFilter) {
    const params = new URLSearchParams(searchParams)
    if (next === 'all') {
      params.delete('surface')
    } else {
      params.set('surface', next)
    }
    setSearchParams(params)
  }

  return (
    <main className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Overview</h1>
          <p className="mt-1 text-sm text-text-secondary">
            Action items first. Statistics and trends are secondary.
          </p>
        </div>
        <label className="text-sm text-text-secondary">
          Surface
          <select
            aria-label="Surface"
            className="ml-2 min-h-10 rounded-md border border-border bg-background px-2 text-sm text-text-primary"
            value={surface}
            onChange={(event) => setSurface(event.target.value as SurfaceFilter)}
          >
            <option value="all">All surfaces</option>
            <option value="local">Local</option>
            <option value="github">GitHub</option>
          </select>
        </label>
      </div>

      <section aria-labelledby="attention-heading">
        <h2 id="attention-heading" className="text-sm font-semibold text-text-primary">
          Needs attention · {lists.attention.length}
        </h2>
        {lists.attention.length === 0 ? (
          <EmptyState
            className="mt-3"
            title="No reviews need attention"
            description="Blocked, Error, and awaiting reviews will appear here."
          />
        ) : (
          <div className="mt-3 grid gap-2">
            {lists.attention.map((summary) => (
              <ReviewSummaryCard key={summary.attemptId} summary={summary} />
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <section aria-labelledby="active-heading" className="xl:col-span-2">
          <h2 id="active-heading" className="text-sm font-semibold text-text-primary">
            Active reviews
          </h2>
          {lists.active.length === 0 ? (
            <EmptyState
              className="mt-3"
              title="No active reviews"
              description="Running pipeline attempts will appear here."
            />
          ) : (
            <div className="mt-3 grid gap-2">
              {lists.active.map((summary) => (
                <ReviewSummaryCard key={summary.attemptId} summary={summary} />
              ))}
            </div>
          )}
        </section>
        <section aria-labelledby="session-insight-heading">
          <h2 id="session-insight-heading" className="text-sm font-semibold text-text-primary">
            Session Insight
          </h2>
          <div className="mt-3 rounded-md border border-border bg-surface p-3">
            <SessionInsightCard status={overview.sessionInsight} />
          </div>
        </section>
      </div>

      <section aria-labelledby="recent-heading">
        <h2 id="recent-heading" className="text-sm font-semibold text-text-primary">
          Recent attempts
        </h2>
        {lists.recent.length === 0 ? (
          <EmptyState className="mt-3" title="No recent attempts" description="Completed attempts will appear here." />
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-border text-text-secondary">
                  <th className="py-2 pr-3 font-medium">Repository</th>
                  <th className="py-2 pr-3 font-medium">Gate</th>
                  <th className="py-2 pr-3 font-medium">Findings</th>
                  <th className="py-2 pr-3 font-medium">Duration</th>
                  <th className="py-2 pr-3 font-medium">Model</th>
                  <th className="py-2 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {lists.recent.map((summary) => {
                  const gate = gateBadge(summary.gateState)
                  return (
                    <tr key={summary.attemptId} className="border-b border-border">
                      <td className="py-2 pr-3">
                        <Link
                          className="text-text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                          to={`/reviews/${summary.attemptId}`}
                        >
                          {summary.repositoryDisplayName}
                        </Link>
                      </td>
                      <td className="py-2 pr-3">
                        <Badge tone={gate.tone} label={gate.label} />
                      </td>
                      <td className="py-2 pr-3 tabular-nums">{summary.findingCount}</td>
                      <td className="py-2 pr-3 tabular-nums">{formatDuration(summary.durationMs)}</td>
                      <td className="py-2 pr-3">
                        {summary.provider} / {summary.model}
                      </td>
                      <td className="py-2 tabular-nums">{formatCost(summary.costUsd, summary.costUnknown)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <StatsStrip stats={overview.stats} />
      <OverviewCharts overview={overview} />

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-border bg-surface p-3">
          <h2 className="text-sm font-semibold">Finding severity</h2>
          <ul className="mt-3 space-y-2">
            {overview.findingSeverity.map((item) => (
              <li key={item.severity} className="flex items-center gap-2 text-sm">
                <Badge
                  tone={
                    item.severity === 'critical'
                      ? 'critical'
                      : item.severity === 'major'
                        ? 'major'
                        : item.severity === 'minor'
                          ? 'minor'
                          : 'suggestion'
                  }
                  label={item.severity}
                />
                <span className="tabular-nums text-text-secondary">{item.count}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-md border border-border bg-surface p-3">
          <h2 className="text-sm font-semibold">Policy usage</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {overview.policyUsage.map((item) => (
              <li key={item.reviewPolicyVersion}>
                Review Policy {item.reviewPolicyVersion}: {item.reviewCount} reviews, {item.blockedCount}{' '}
                blocked, {item.errorCount} error
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-md border border-border bg-surface p-3">
          <h2 className="text-sm font-semibold">Dimension health</h2>
          <ul className="mt-3 space-y-2 text-sm text-text-secondary">
            {overview.dimensionHealth.map((item) => (
              <li key={item.dimensionId}>
                {item.dimensionId}: {item.completedCount} completed, {item.failedCount} failed
                {item.averageElapsedMs === null
                  ? ''
                  : `, avg ${String(Math.round(item.averageElapsedMs / 1000))}s`}
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-md border border-border bg-surface p-3">
          <h2 className="text-sm font-semibold">Provider health</h2>
          <ul className="mt-3 space-y-2 text-sm text-text-secondary">
            {overview.providerHealth.map((item) => (
              <li key={item.profileName}>
                {item.profileName}: {item.status.replaceAll('_', ' ')}
                {item.observedAt ? ` at ${item.observedAt}` : ''}
                . This is last observed status, not a live probe.
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  )
}
