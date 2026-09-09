import type { OverviewStatsView } from '../../domain/overview.ts'
import { formatCost, formatDuration, formatPercent } from './format.ts'

export function StatsStrip({ stats }: { stats: OverviewStatsView }) {
  return (
    <section aria-labelledby="overview-stats-heading" className="border-t border-border pt-6">
      <h2 id="overview-stats-heading" className="text-sm font-semibold text-text-primary">
        Statistics
      </h2>
      <p className="mt-1 text-xs text-text-secondary">
        Gate pass rate is Passed / (Passed + Blocked). Error is excluded from that denominator.
        Unknown cost is counted separately and is never stored or shown as $0.00.
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Attempts" value={String(stats.attemptCount)} />
        <Stat label="Gate pass rate" value={formatPercent(stats.gatePassRate)} />
        <Stat label="Blocked" value={String(stats.blockedCount)} />
        <Stat label="Error rate" value={formatPercent(stats.errorRate)} />
        <Stat label="Average duration" value={formatDuration(stats.averageDurationMs)} />
        <Stat
          label="Known model cost"
          value={`${formatCost(stats.knownCostUsd, false)} · ${String(stats.unknownCostRecordCount)} unknown`}
        />
      </div>
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="mt-1 font-medium tabular-nums text-text-primary">{value}</p>
    </div>
  )
}
