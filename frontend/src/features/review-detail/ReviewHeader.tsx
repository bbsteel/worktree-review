import { GitPullRequest, HardDrive } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '../../components/ui/badge.tsx'
import type { ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { CopyValue } from './CopyValue.tsx'
import { formatCostUsd, formatDurationMs, formatTimestamp } from './formatting.ts'
import {
  AUTHORITY_PRESENTATION,
  BYPASS_PRESENTATION,
  GATE_PRESENTATION,
  PUBLICATION_PRESENTATION,
  RUN_STATUS_PRESENTATION,
  SOURCE_KIND_LABEL,
} from './presentation.ts'
import { ReviewActionsBar } from './ReviewActionsBar.tsx'

interface ReviewHeaderProps {
  run: ReviewRunView
  /** Jump entry to the Findings tab for the per-finding Accept-risk actions. */
  onShowFindings?: () => void
}

function MetaItem({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <dt className="text-meta uppercase tracking-wide text-text-secondary">{term}</dt>
      <dd className="text-sm text-text-primary">{children}</dd>
    </div>
  )
}

/**
 * P3 §9.3 standing wording: the platform decision and the remote Check sync
 * are always explained with icon-free text plus the badges, never by color
 * alone. Returns null when there is nothing standing-related to say.
 */
function standingStatusText(
  run: ReviewRunView,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string | null {
  if (run.standingGateState === undefined || run.standingGateState === null) {
    return null
  }
  if (run.authority === 'superseded' && run.bypassState !== 'none') {
    return t('Superseded · bypass retained for audit, no longer applicable')
  }
  if (run.standingGateState === 'Passed with bypass') {
    if (run.checkSyncStatus === 'published') {
      return t('Passed with bypass · GitHub Check updated')
    }
    if (run.checkSyncStatus === 'failed') {
      return t('Risk acceptance recorded; GitHub Check is still blocking. Retry sync.')
    }
    return t('Passed with bypass · GitHub Check sync pending')
  }
  const remaining = run.gate.remainingBlockingFingerprints?.length ?? 0
  if (run.bypassState === 'active' && remaining > 0) {
    return t('Risk accepted for some findings · {count} blocking findings remain', {
      count: remaining,
    })
  }
  return null
}

/**
 * Source-adaptive Review Detail header (design 13.1/13.2).
 * Local sources never render PR/author fields; GitHub sources never render
 * local worktree paths. Gate status always pairs icon, text and color.
 */
export function ReviewHeader({ run, onShowFindings }: ReviewHeaderProps) {
  const { t } = useI18n()
  const gate = GATE_PRESENTATION[run.gateState]
  const authority = AUTHORITY_PRESENTATION[run.authority]
  const runStatus = RUN_STATUS_PRESENTATION[run.runStatus]
  const source = run.source
  const standingText = standingStatusText(run, t)

  return (
    <header className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm text-text-secondary">
            {source.kind === 'github-pull-request' ? (
              <GitPullRequest aria-hidden="true" className="h-4 w-4" />
            ) : (
              <HardDrive aria-hidden="true" className="h-4 w-4" />
            )}
            <span>{t(SOURCE_KIND_LABEL[source.kind])}</span>
          </div>

          {source.kind === 'github-pull-request' ? (
            <>
              <h1 className="mt-1 text-xl font-semibold text-text-primary">
                {source.repositoryFullName} · PR #{source.pullRequestNumber}
              </h1>
              <p className="mt-0.5 text-sm text-text-secondary">{source.pullRequestTitle}</p>
              <p className="mt-1 font-mono text-sm text-text-primary">
                {source.proposedBranch} → {source.targetBranch}
              </p>
            </>
          ) : (
            <>
              <h1 className="mt-1 text-xl font-semibold text-text-primary">
                {source.repositoryDisplayName}
              </h1>
              <p className="mt-1 font-mono text-sm text-text-primary">
                {source.targetRef ?? 'HEAD'} → {source.proposedRef ?? source.worktreeLabel ?? 'WORKTREE'}
              </p>
            </>
          )}
        </div>

        <div className="flex flex-col items-end gap-2">
          <Badge tone={gate.tone} label={t(gate.label)} className="px-3 py-1.5 text-sm" />
          {run.runStatus !== 'completed' ? (
            <span className="text-meta text-text-secondary">
              {t('Run status: {label} — {description}', {
                label: t(runStatus.label),
                description: t(runStatus.description),
              })}
            </span>
          ) : null}
        </div>
      </div>

      <p className="mt-3 text-sm text-text-primary">{run.gate.summary}</p>
      <p className="mt-1 text-meta text-text-secondary">{t(gate.description)}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge tone={authority.tone} label={t(authority.label)} />
        <span className="text-meta text-text-secondary">{t(authority.description)}</span>
        {run.bypassState !== 'none' ? (
          <Badge
            tone={BYPASS_PRESENTATION[run.bypassState].tone}
            label={t(BYPASS_PRESENTATION[run.bypassState].label)}
          />
        ) : null}
        {run.publicationStatus !== 'not_applicable' ? (
          <Badge tone="neutral" label={t(PUBLICATION_PRESENTATION[run.publicationStatus].label)} />
        ) : null}
      </div>

      {standingText !== null ? (
        <p role="status" className="mt-2 text-sm text-text-secondary">
          {standingText}
        </p>
      ) : null}

      <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-3">
        {source.kind === 'github-pull-request' ? (
          <MetaItem term={t('Author')}>{source.authorLogin}</MetaItem>
        ) : null}
        <MetaItem term={t('Provider / Model')}>
          {run.summary.provider} / {run.summary.model}
        </MetaItem>
        <MetaItem term={t('Review Policy')}>{run.policies.reviewPolicyVersion}</MetaItem>
        <MetaItem term={t('Attempt')}>
          <CopyValue value={run.attemptId} label="Attempt ID" truncate={false} />
        </MetaItem>
        <MetaItem term={t('Duration')}>{t(formatDurationMs(run.summary.durationMs))}</MetaItem>
        <MetaItem term={t('Cost')}>{t(formatCostUsd(run.summary.costUsd, run.summary.costUnknown))}</MetaItem>
        {source.kind === 'github-pull-request' ? (
          <MetaItem term={t('Commit')}>
            <CopyValue value={source.commitSha} label={t('commit SHA')} />
          </MetaItem>
        ) : null}
        {source.kind !== 'github-pull-request' && source.snapshotSha !== null ? (
          <MetaItem term={t('Snapshot')}>
            <CopyValue value={source.snapshotSha} label={t('snapshot SHA')} />
          </MetaItem>
        ) : null}
        <MetaItem term={t('Created')}>{formatTimestamp(run.summary.createdAt)}</MetaItem>
      </dl>

      <div className="mt-4 border-t border-border pt-3">
        <ReviewActionsBar run={run} onShowFindings={onShowFindings} />
      </div>
    </header>
  )
}
