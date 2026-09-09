import { GitPullRequest, HardDrive } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '../../components/ui/badge.tsx'
import type { ReviewRunView } from '../../domain/review.ts'
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
 * Source-adaptive Review Detail header (design 13.1/13.2).
 * Local sources never render PR/author fields; GitHub sources never render
 * local worktree paths. Gate status always pairs icon, text and color.
 */
export function ReviewHeader({ run }: ReviewHeaderProps) {
  const gate = GATE_PRESENTATION[run.gateState]
  const authority = AUTHORITY_PRESENTATION[run.authority]
  const runStatus = RUN_STATUS_PRESENTATION[run.runStatus]
  const source = run.source

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
            <span>{SOURCE_KIND_LABEL[source.kind]}</span>
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
          <Badge tone={gate.tone} label={gate.label} className="px-3 py-1.5 text-sm" />
          {run.runStatus !== 'completed' ? (
            <span className="text-meta text-text-secondary">
              Run status: {runStatus.label} — {runStatus.description}
            </span>
          ) : null}
        </div>
      </div>

      <p className="mt-3 text-sm text-text-primary">{run.gate.summary}</p>
      <p className="mt-1 text-meta text-text-secondary">{gate.description}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge tone={authority.tone} label={authority.label} />
        <span className="text-meta text-text-secondary">{authority.description}</span>
        {run.bypassState !== 'none' ? (
          <Badge
            tone={BYPASS_PRESENTATION[run.bypassState].tone}
            label={BYPASS_PRESENTATION[run.bypassState].label}
          />
        ) : null}
        {run.publicationStatus !== 'not_applicable' ? (
          <Badge tone="neutral" label={PUBLICATION_PRESENTATION[run.publicationStatus].label} />
        ) : null}
      </div>

      <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-3">
        {source.kind === 'github-pull-request' ? (
          <MetaItem term="Author">{source.authorLogin}</MetaItem>
        ) : null}
        <MetaItem term="Provider / Model">
          {run.summary.provider} / {run.summary.model}
        </MetaItem>
        <MetaItem term="Review Policy">{run.policies.reviewPolicyVersion}</MetaItem>
        <MetaItem term="Attempt">
          <CopyValue value={run.attemptId} label="Attempt ID" truncate={false} />
        </MetaItem>
        <MetaItem term="Duration">{formatDurationMs(run.summary.durationMs)}</MetaItem>
        <MetaItem term="Cost">{formatCostUsd(run.summary.costUsd, run.summary.costUnknown)}</MetaItem>
        {source.kind === 'github-pull-request' ? (
          <MetaItem term="Commit">
            <CopyValue value={source.commitSha} label="commit SHA" />
          </MetaItem>
        ) : null}
        {source.kind !== 'github-pull-request' && source.snapshotSha !== null ? (
          <MetaItem term="Snapshot">
            <CopyValue value={source.snapshotSha} label="snapshot SHA" />
          </MetaItem>
        ) : null}
        <MetaItem term="Created">{formatTimestamp(run.summary.createdAt)}</MetaItem>
      </dl>

      <div className="mt-4 border-t border-border pt-3">
        <ReviewActionsBar run={run} />
      </div>
    </header>
  )
}
