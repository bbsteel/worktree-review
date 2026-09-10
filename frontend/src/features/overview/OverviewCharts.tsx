import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { usePrefersReducedMotion } from '../../app/motion.ts'
import type { OverviewView } from '../../domain/overview.ts'
import { BLOCKED_COST_USD, PASSED_COST_USD } from '../../data/fixtures/constants.ts'
import { useI18n } from '../../i18n.tsx'

export function OverviewCharts({ overview }: { overview: OverviewView }) {
  const reduced = usePrefersReducedMotion()
  const { t } = useI18n()
  const costTrend = overview.gateTrend.map((point) => ({
    date: point.date.slice(5),
    knownCost: Number((point.passed * PASSED_COST_USD + point.blocked * BLOCKED_COST_USD).toFixed(2)),
    unknownAttempts: point.error,
  }))

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard
        title={t('Gate trend')}
        caption={t('Daily Passed, Blocked, Error, and In Progress. Charts show trend only; exact counts are in Statistics.')}
      >
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={overview.gateTrend} accessibilityLayer>
            <CartesianGrid stroke="var(--wr-border)" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: 'var(--wr-text-secondary)', fontSize: 12 }} />
            <YAxis allowDecimals={false} tick={{ fill: 'var(--wr-text-secondary)', fontSize: 12 }} />
            <Tooltip />
            <Legend formatter={(value) => t(String(value))} />
            <Bar dataKey="passed" stackId="gate" fill="var(--wr-status-passed)" isAnimationActive={!reduced} />
            <Bar dataKey="blocked" stackId="gate" fill="var(--wr-status-blocked)" isAnimationActive={!reduced} />
            <Bar dataKey="error" stackId="gate" fill="var(--wr-status-error)" isAnimationActive={!reduced} />
            <Bar
              dataKey="inProgress"
              stackId="gate"
              fill="var(--wr-status-running)"
              isAnimationActive={!reduced}
            />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>
      <ChartCard
        title={t('Token and cost trend')}
        caption={t(
          'Known cost scales Passed at ${passed} and Blocked at ${blocked} from demo cases. Error days add unknown-cost attempts, not $0.00.',
          { passed: PASSED_COST_USD.toFixed(2), blocked: BLOCKED_COST_USD.toFixed(2) },
        )}
      >
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={costTrend} accessibilityLayer>
            <CartesianGrid stroke="var(--wr-border)" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: 'var(--wr-text-secondary)', fontSize: 12 }} />
            <YAxis tick={{ fill: 'var(--wr-text-secondary)', fontSize: 12 }} />
            <Tooltip />
            <Legend formatter={(value) => t(String(value))} />
            <Bar dataKey="knownCost" fill="var(--wr-action-primary)" isAnimationActive={!reduced} />
            <Bar dataKey="unknownAttempts" fill="var(--wr-status-warning)" isAnimationActive={!reduced} />
          </BarChart>
        </ResponsiveContainer>
        <p className="mt-2 text-xs text-text-secondary">
          {t('Known tokens (demo cases)')}: {overview.stats.knownInputTokens.toLocaleString()} {t('in')} /{' '}
          {overview.stats.knownOutputTokens.toLocaleString()} {t('out')}
        </p>
      </ChartCard>
    </div>
  )
}

function ChartCard({ title, caption, children }: { title: string; caption: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-surface p-3">
      <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      <p className="mt-1 text-xs text-text-secondary">{caption}</p>
      <div className="mt-3">{children}</div>
    </section>
  )
}
