import { Badge } from '../../components/ui/badge.tsx'
import { EmptyState } from '../../components/ui/empty-state.tsx'
import { cx } from '../../components/ui/cx.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import { CopyValue } from './CopyValue.tsx'
import { formatCostUsd, formatDurationMs, formatTimestamp, formatTokenCount } from './formatting.ts'
import { AUTHORITY_PRESENTATION, GATE_PRESENTATION, SOURCE_KIND_LABEL } from './presentation.ts'

/**
 * Attempt timeline for one Review Request (design 13.7). The current
 * authoritative attempt is emphasized; superseded attempts always carry the
 * loss-of-authority explanation. Attempts are immutable history — a retry
 * creates a new attempt and never overwrites an old one.
 */
export function AttemptsTab({ run }: { run: ReviewRunView }) {
  if (run.attempts.length === 0) {
    return (
      <EmptyState
        title="No attempts recorded"
        description="This view lists every attempt of the review request. The current attempt is missing from history, which indicates an incomplete record."
      />
    )
  }

  return (
    <section aria-label="Attempt timeline" className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-text-primary">Attempts</h2>
      <ol className="mt-3 flex flex-col gap-2">
        {run.attempts.map((attempt) => {
          const authority = AUTHORITY_PRESENTATION[attempt.authority]
          const gate = GATE_PRESENTATION[attempt.gateState]
          const isCurrent = attempt.attemptId === run.attemptId
          const isAuthoritative = attempt.authority === 'authoritative'

          return (
            <li
              key={attempt.attemptId}
              aria-current={isCurrent ? 'true' : undefined}
              className={cx(
                'rounded-md border px-3 py-2',
                isAuthoritative ? 'border-action-primary' : 'border-border',
                attempt.authority === 'superseded' ? 'opacity-80' : undefined,
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={gate.tone} label={gate.label} />
                <Badge tone={authority.tone} label={authority.label} />
                {isCurrent ? <Badge tone="neutral" label="Current attempt" /> : null}
                <CopyValue value={attempt.attemptId} label="Attempt ID" truncate={false} />
              </div>
              <p className="mt-1 text-meta text-text-secondary">{authority.description}</p>
              <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-meta sm:grid-cols-2 lg:grid-cols-3">
                <div className="flex gap-1.5">
                  <dt className="text-text-secondary">Trigger</dt>
                  <dd className="text-text-primary">
                    {SOURCE_KIND_LABEL[attempt.trigger as keyof typeof SOURCE_KIND_LABEL] ??
                      attempt.trigger}
                  </dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-text-secondary">Provider / Model</dt>
                  <dd className="font-mono text-text-primary">
                    {attempt.provider} / {attempt.model}
                  </dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-text-secondary">Policies</dt>
                  <dd className="font-mono text-text-primary">
                    review {attempt.reviewPolicyVersion} · compute {attempt.computePolicyVersion}
                  </dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-text-secondary">Tokens</dt>
                  <dd className="text-text-primary tabular-nums">
                    {formatTokenCount(attempt.tokenCount)}
                  </dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-text-secondary">Cost</dt>
                  <dd className="text-text-primary tabular-nums">
                    {formatCostUsd(attempt.costUsd, attempt.costUnknown)}
                  </dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-text-secondary">Started · Duration</dt>
                  <dd className="text-text-primary tabular-nums">
                    {formatTimestamp(attempt.startedAt)} · {formatDurationMs(attempt.durationMs)}
                  </dd>
                </div>
              </dl>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
