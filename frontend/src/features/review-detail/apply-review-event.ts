/**
 * Apply live ReviewEvents to a ReviewRunView (design 4.2, 16.5).
 *
 * Only events with enough payload to update the view deterministically are
 * applied here. Anything that changes gate, findings or final results
 * triggers a full refetch by the caller instead of partial client-side
 * reconstruction. Payload fields that are absent leave the view unchanged —
 * the UI never invents progress.
 */
import type { ReviewEventDto } from '../../data/api/dto.ts'
import type {
  PipelineStageStatus,
  ReviewRunView,
  RunStatus,
} from '../../domain/review.ts'

export interface EventApplication {
  run: ReviewRunView
  /** True when the caller should refetch the authoritative run view. */
  refetch: boolean
}

function payloadString(event: ReviewEventDto, key: string): string | null {
  const value = event.payload[key]
  return typeof value === 'string' ? value : null
}

function payloadNumber(event: ReviewEventDto, key: string): number | null {
  const value = event.payload[key]
  return typeof value === 'number' && !Number.isNaN(value) ? value : null
}

function setStageStatus(
  run: ReviewRunView,
  stage: string,
  status: PipelineStageStatus,
  elapsedMs: number | null,
  safeError: string | null,
): ReviewRunView {
  return {
    ...run,
    pipeline: run.pipeline.map((existing) =>
      existing.stage === stage
        ? {
            ...existing,
            status,
            elapsedMs: elapsedMs ?? existing.elapsedMs,
            safeError: safeError ?? existing.safeError,
          }
        : existing,
    ),
  }
}

const STAGE_NAMES = new Set<string>([
  'derive-identity',
  'construct-merge',
  'prepare-review-worktree',
  'gather-context',
  'run-dimensions',
  'verify-dedup',
  'check-completeness',
  'evaluate-gate',
  'publish',
])

export function applyReviewEvent(run: ReviewRunView, event: ReviewEventDto): EventApplication {
  const stageName = payloadString(event, 'stage')

  switch (event.event_type) {
    case 'stage.started': {
      if (stageName === null || !STAGE_NAMES.has(stageName)) {
        return { run, refetch: false }
      }
      return {
        run: {
          ...setStageStatus(run, stageName, 'running', null, null),
          runStatus: 'running' satisfies RunStatus,
          gateState: run.gateState === 'awaiting_review' ? 'in_progress' : run.gateState,
        },
        refetch: false,
      }
    }
    case 'stage.completed': {
      if (stageName === null || !STAGE_NAMES.has(stageName)) {
        return { run, refetch: false }
      }
      return {
        run: setStageStatus(run, stageName, 'completed', payloadNumber(event, 'elapsed_ms'), null),
        refetch: false,
      }
    }
    case 'stage.failed': {
      // Failure rewrites gate and failure projections; refetch the truth.
      return { run, refetch: true }
    }
    case 'dimension.started': {
      const dimensionId = payloadString(event, 'dimension_id')
      if (dimensionId === null) {
        return { run, refetch: false }
      }
      return {
        run: {
          ...run,
          dimensions: run.dimensions.map((dimension) =>
            dimension.dimensionId === dimensionId
              ? { ...dimension, status: 'running' }
              : dimension,
          ),
        },
        refetch: false,
      }
    }
    case 'dimension.completed': {
      const dimensionId = payloadString(event, 'dimension_id')
      if (dimensionId === null) {
        return { run, refetch: false }
      }
      return {
        run: {
          ...run,
          dimensions: run.dimensions.map((dimension) =>
            dimension.dimensionId === dimensionId
              ? {
                  ...dimension,
                  status: 'completed',
                  elapsedMs: payloadNumber(event, 'elapsed_ms') ?? dimension.elapsedMs,
                }
              : dimension,
          ),
        },
        refetch: false,
      }
    }
    case 'dimension.failed': {
      const dimensionId = payloadString(event, 'dimension_id')
      if (dimensionId === null) {
        return { run, refetch: false }
      }
      return {
        run: {
          ...run,
          dimensions: run.dimensions.map((dimension) =>
            dimension.dimensionId === dimensionId
              ? { ...dimension, status: 'failed' }
              : dimension,
          ),
        },
        refetch: false,
      }
    }
    case 'gate.evaluated':
    case 'attempt.completed':
      return { run, refetch: true }
    default:
      // attempt.created, inputs.resolved, provider_call.*, finding.*,
      // call_plan.ready, coverage.recorded: not projected client-side.
      return { run, refetch: false }
  }
}

export function isTerminalRunStatus(status: RunStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'interrupted'
}
