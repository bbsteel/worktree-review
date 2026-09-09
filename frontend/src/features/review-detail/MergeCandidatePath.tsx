import { Circle, CircleCheck, CircleDot, CircleX, MoveRight, type LucideIcon } from 'lucide-react'
import { cx } from '../../components/ui/cx.ts'
import type { PipelineStageName, PipelineStageStatus, ReviewRunView } from '../../domain/review.ts'
import { PIPELINE_STAGE_LABEL, STAGE_STATUS_PRESENTATION } from './presentation.ts'

interface ConceptNode {
  key: string
  label: string
  stage: PipelineStageName
}

const CONCEPT_NODES: ConceptNode[] = [
  { key: 'inputs', label: 'Target + Proposed', stage: 'derive-identity' },
  { key: 'merge', label: 'Exact Merge Tree', stage: 'construct-merge' },
  { key: 'worktree', label: 'Read-only Review Worktree', stage: 'prepare-review-worktree' },
  { key: 'context', label: 'Context', stage: 'gather-context' },
  { key: 'dimensions', label: 'Review Dimensions', stage: 'run-dimensions' },
  { key: 'verification', label: 'Evidence Verification', stage: 'verify-dedup' },
  { key: 'gate', label: 'Gate Decision', stage: 'evaluate-gate' },
]

const STATUS_ICON: Record<PipelineStageStatus, LucideIcon> = {
  'not-started': Circle,
  running: CircleDot,
  completed: CircleCheck,
  failed: CircleX,
}

const STATUS_CLASS: Record<PipelineStageStatus, string> = {
  'not-started': 'text-text-secondary border-border',
  running: 'text-status-running border-status-running',
  completed: 'text-status-passed border-border',
  failed: 'text-status-error border-status-error',
}

/**
 * Concept path for what was reviewed (design 13.3): the exact merge result,
 * not a plain diff. Node state is projected from the real pipeline stages; a
 * failed merge terminates the path and the Gate node only reaches a terminal
 * state after completeness and gate evaluation finished.
 */
export function MergeCandidatePath({ run }: { run: ReviewRunView }) {
  const stageByName = new Map(run.pipeline.map((stage) => [stage.stage, stage]))
  const failed = run.pipeline.find((stage) => stage.status === 'failed')

  return (
    <section
      aria-label="Merge candidate review path"
      className="rounded-lg border border-border bg-surface p-4"
    >
      <h2 className="text-sm font-semibold text-text-primary">Merge candidate review path</h2>
      <p className="mt-0.5 text-meta text-text-secondary">
        The reviewed content is the exact merge result of target and proposed heads, evaluated in a
        read-only review worktree.
      </p>

      <ol className="mt-3 flex flex-wrap items-stretch gap-y-2">
        {CONCEPT_NODES.map((node, index) => {
          const stage = stageByName.get(node.stage)
          const status: PipelineStageStatus = stage?.status ?? 'not-started'
          const Icon = STATUS_ICON[status]

          return (
            <li key={node.key} className="flex items-center">
              {index > 0 ? (
                <MoveRight
                  aria-hidden="true"
                  className={cx(
                    'mx-1 h-4 w-4',
                    status === 'running' ? 'animate-pulse text-status-running' : 'text-text-secondary',
                  )}
                />
              ) : null}
              <div
                aria-current={status === 'running' ? 'step' : undefined}
                className={cx(
                  'flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium',
                  STATUS_CLASS[status],
                  status === 'running' ? 'animate-pulse' : undefined,
                  status === 'not-started' ? 'opacity-70' : undefined,
                )}
              >
                <Icon aria-hidden="true" className="h-3.5 w-3.5" />
                <span>{node.label}</span>
                <span className="sr-only">{STAGE_STATUS_PRESENTATION[status].label}</span>
              </div>
            </li>
          )
        })}
      </ol>

      {failed !== undefined ? (
        <p role="alert" className="mt-3 text-sm text-status-error">
          {PIPELINE_STAGE_LABEL[failed.stage]} failed — the review path stops at this node. The safe
          failure detail is shown in the pipeline section below.
        </p>
      ) : null}
    </section>
  )
}
