import { Circle, CircleCheck, CircleDot, CircleX, type LucideIcon } from 'lucide-react'
import { cx } from '../../components/ui/cx.ts'
import type { PipelineStageStatus, PipelineStageView } from '../../domain/review.ts'
import { formatDurationMs } from './formatting.ts'
import { PIPELINE_STAGE_LABEL, STAGE_STATUS_PRESENTATION } from './presentation.ts'

const STATUS_ICON: Record<PipelineStageStatus, LucideIcon> = {
  'not-started': Circle,
  running: CircleDot,
  completed: CircleCheck,
  failed: CircleX,
}

const STATUS_CLASS: Record<PipelineStageStatus, string> = {
  'not-started': 'text-text-secondary',
  running: 'text-status-running',
  completed: 'text-status-passed',
  failed: 'text-status-error',
}

/**
 * Nine-stage execution pipeline (design 13.4). Failed stages stop the data
 * flow and expose their safe error detail through a keyboard-accessible
 * disclosure; unfinished stages stay dimmed. All animation respects
 * prefers-reduced-motion via the global token override.
 */
export function PipelineStages({ stages }: { stages: PipelineStageView[] }) {
  return (
    <ol className="flex flex-col gap-1">
      {stages.map((stage, index) => {
        const Icon = STATUS_ICON[stage.status]
        const statusLabel = STAGE_STATUS_PRESENTATION[stage.status].label

        return (
          <li key={stage.stage}>
            <div
              aria-current={stage.status === 'running' ? 'step' : undefined}
              className={cx(
                'flex items-center gap-3 rounded-md border border-border bg-surface-subtle px-3 py-2',
                stage.status === 'not-started' ? 'opacity-70' : undefined,
              )}
            >
              <span className="w-5 text-right font-mono text-meta text-text-secondary tabular-nums">
                {index + 1}
              </span>
              <Icon
                aria-hidden="true"
                className={cx(
                  'h-4 w-4',
                  STATUS_CLASS[stage.status],
                  stage.status === 'running' ? 'animate-pulse' : undefined,
                )}
              />
              <span className="text-sm font-medium text-text-primary">
                {PIPELINE_STAGE_LABEL[stage.stage]}
              </span>
              <span className={cx('text-meta', STATUS_CLASS[stage.status])}>{statusLabel}</span>
              <span className="ml-auto font-mono text-meta text-text-secondary tabular-nums">
                {stage.elapsedMs !== null ? formatDurationMs(stage.elapsedMs) : ''}
              </span>
            </div>

            {stage.status === 'failed' && stage.safeError !== null ? (
              <details className="mt-1 rounded-md border border-status-error bg-surface px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-status-error focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
                  Failure detail (safe summary)
                </summary>
                <p className="mt-2 whitespace-pre-wrap font-mono text-meta text-text-primary">
                  {stage.safeError}
                </p>
              </details>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
