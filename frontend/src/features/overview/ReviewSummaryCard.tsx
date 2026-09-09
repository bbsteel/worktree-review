import { Link } from 'react-router'
import { Badge } from '../../components/ui/badge.tsx'
import type { ReviewSummaryView } from '../../domain/review.ts'
import { formatCost, formatDuration, gateBadge, sourceLabel } from './format.ts'

export function ReviewSummaryCard({ summary }: { summary: ReviewSummaryView }) {
  const gate = gateBadge(summary.gateState)
  return (
    <Link
      to={`/reviews/${summary.attemptId}`}
      className="block rounded-md border border-border bg-surface px-3 py-3 hover:border-action-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={gate.tone} label={gate.label} />
        <span className="font-medium text-text-primary">{summary.repositoryDisplayName}</span>
        <span className="text-sm text-text-secondary">{sourceLabel(summary.source)}</span>
      </div>
      <p className="mt-2 text-sm text-text-secondary">
        {summary.findingCount} finding{summary.findingCount === 1 ? '' : 's'}
        {' · '}
        {formatDuration(summary.durationMs)}
        {' · '}
        {formatCost(summary.costUsd, summary.costUnknown)}
        {' · '}
        {summary.provider} / {summary.model}
      </p>
    </Link>
  )
}
