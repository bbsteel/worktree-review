import { Circle, CircleCheck, CircleDot, CircleX, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '../../components/ui/badge.tsx'
import type { DimensionStatus, ReviewRunView } from '../../domain/review.ts'
import { formatCostUsd, formatDurationMs, formatTimestamp } from './formatting.ts'
import { PipelineStages } from './PipelineStages.tsx'
import { GATE_PRESENTATION, PIPELINE_STAGE_LABEL } from './presentation.ts'

const DIMENSION_STATUS_ICON: Record<DimensionStatus, LucideIcon> = {
  'not-started': Circle,
  running: CircleDot,
  completed: CircleCheck,
  failed: CircleX,
}

const DIMENSION_STATUS_TEXT: Record<DimensionStatus, { label: string; className: string }> = {
  'not-started': { label: 'Not started', className: 'text-text-secondary' },
  running: { label: 'Running', className: 'text-status-running' },
  completed: { label: 'Completed', className: 'text-status-passed' },
  failed: { label: 'Failed', className: 'text-status-error' },
}

function SummaryTile({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface-subtle p-3">
      <h3 className="text-meta uppercase tracking-wide text-text-secondary">{title}</h3>
      <div className="mt-2">{children}</div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  )
}

/**
 * Overview tab (design 13.4): gate, blocking, coverage and cost summaries
 * first, then review summary, dynamic dimensions and the nine-stage pipeline,
 * then provider and data disclosure. Dimension ids come from the actual run;
 * they are never hard-coded.
 */
export function OverviewTab({ run }: { run: ReviewRunView }) {
  const gate = GATE_PRESENTATION[run.gateState]
  const gateEvaluated = run.gateState === 'passed' || run.gateState === 'blocked'
  const blockingCount = run.gate.blockingFingerprints.length
  const health = run.providerHealth

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryTile title="Gate Decision">
          <Badge tone={gate.tone} label={gate.label} />
        </SummaryTile>

        <SummaryTile title="Blocking Findings">
          {gateEvaluated ? (
            <p className="text-lg font-semibold text-text-primary tabular-nums">
              {blockingCount}
              <span className="ml-1 text-sm font-normal text-text-secondary">
                {blockingCount === 1 ? 'finding' : 'findings'}
              </span>
            </p>
          ) : (
            <p className="text-sm text-text-secondary">
              Not evaluated — the review did not reach gate evaluation.
            </p>
          )}
        </SummaryTile>

        <SummaryTile title="Required Coverage">
          <p className="text-sm font-medium text-text-primary">
            {run.coverage.requiredCoverage === 'complete' ? 'Complete' : 'Incomplete'}
          </p>
          <p className="text-meta text-text-secondary">
            {run.coverage.reviewedCount} reviewed · {run.coverage.missingCount} missing ·{' '}
            {run.coverage.excludedCount} excluded
          </p>
        </SummaryTile>

        <SummaryTile title="Cost (estimated / actual)">
          <p className="text-sm font-medium text-text-primary tabular-nums">
            {formatCostUsd(run.usage.estimatedCostUsd, run.usage.costUnknown)} /{' '}
            {formatCostUsd(run.usage.actualCostUsd, run.usage.costUnknown)}
          </p>
          {run.usage.costUnknown ? (
            <p className="text-meta text-status-warning">
              Actual cost unknown for {run.usage.unknownCostRecordCount} record
              {run.usage.unknownCostRecordCount === 1 ? '' : 's'}.
            </p>
          ) : null}
        </SummaryTile>
      </div>

      {run.failure !== null ? (
        <section
          aria-label="Failure detail"
          className="rounded-lg border border-status-error bg-surface p-4"
        >
          <h2 className="text-sm font-semibold text-status-error">
            {PIPELINE_STAGE_LABEL[run.failure.stage]} failed — {run.failure.category}
          </h2>
          <p className="mt-2 whitespace-pre-wrap font-mono text-meta text-text-primary">
            {run.failure.safeDetail}
          </p>
          <p className="mt-2 text-sm text-text-secondary">
            Stages that completed are shown below; stages after the failure never started. Fix the
            cause, then retry — a retry always creates a new attempt and never overwrites this one.
          </p>
        </section>
      ) : null}

      <Section title="Review Summary">
        <p className="text-sm text-text-primary">{run.gate.summary}</p>
      </Section>

      <Section title="Required Dimensions">
        {run.dimensions.length === 0 ? (
          <p className="text-sm text-text-secondary">
            No dimensions were scheduled by the Review Policy for this attempt.
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {run.dimensions.map((dimension) => {
              const status = DIMENSION_STATUS_TEXT[dimension.status]
              const Icon = DIMENSION_STATUS_ICON[dimension.status]
              return (
                <li
                  key={dimension.dimensionId}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface-subtle px-3 py-2"
                >
                  <Icon
                    aria-hidden="true"
                    className={`h-4 w-4 ${status.className} ${dimension.status === 'running' ? 'animate-pulse' : ''}`}
                  />
                  <span className="font-mono text-sm text-text-primary">{dimension.dimensionId}</span>
                  <span className={`text-meta ${status.className}`}>{status.label}</span>
                  <span className="ml-auto flex items-center gap-3 text-meta text-text-secondary tabular-nums">
                    {dimension.elapsedMs !== null ? (
                      <span>{formatDurationMs(dimension.elapsedMs)}</span>
                    ) : null}
                    <span>
                      {dimension.findingCount} finding{dimension.findingCount === 1 ? '' : 's'}
                      {dimension.blockingFindingCount > 0
                        ? ` · ${dimension.blockingFindingCount} blocking`
                        : ''}
                    </span>
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <Section title="Review Pipeline">
        <PipelineStages stages={run.pipeline} />
      </Section>

      <Section title="Provider & Data Disclosure">
        <dl className="flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">Provider / Model</dt>
            <dd className="font-mono text-text-primary">
              {run.summary.provider} / {run.summary.model}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">Data destination</dt>
            <dd className="text-text-primary">{run.policies.dataDestination}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">Known retention</dt>
            <dd className="text-text-primary">{run.policies.retentionDisclosure}</dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">Provider health</dt>
            <dd className="text-text-primary">
              {health.status === 'healthy'
                ? `Healthy at ${formatTimestamp(health.observedAt)}`
                : health.status === 'last_call_failed'
                  ? `Last call failed at ${formatTimestamp(health.observedAt)}`
                  : 'Not tested'}
            </dd>
          </div>
        </dl>
      </Section>
    </div>
  )
}
