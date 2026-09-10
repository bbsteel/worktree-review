import { Link } from 'react-router'
import { Badge } from '../../components/ui/badge.tsx'
import type { ReviewSummaryView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { formatCost, formatDuration, gateBadge, sourceLabel } from './format.ts'

export function ReviewSummaryCard({ summary }: { summary: ReviewSummaryView }) {
  const { t } = useI18n()
  const gate = gateBadge(summary.gateState)
  return (
    <Link
      to={`/reviews/${summary.attemptId}`}
      className="block rounded-md border border-border bg-surface px-3 py-3 hover:border-action-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={gate.tone} label={t(gate.label)} />
        <span className="font-medium text-text-primary">{summary.repositoryDisplayName}</span>
        <span className="text-sm text-text-secondary">{t(sourceLabel(summary.source))}</span>
      </div>
      <p className="mt-2 text-sm text-text-secondary">
        {summary.findingCount} {t(summary.findingCount === 1 ? 'finding' : 'findings')}
        {' · '}
        {t(formatDuration(summary.durationMs))}
        {' · '}
        {t(formatCost(summary.costUsd, summary.costUnknown))}
        {' · '}
        {summary.provider} / {summary.model}
      </p>
    </Link>
  )
}
