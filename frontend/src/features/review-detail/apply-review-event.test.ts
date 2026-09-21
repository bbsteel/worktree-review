import { describe, expect, it } from 'vitest'
import type { ReviewEventDto } from '../../data/api/dto.ts'
import { blockedCase } from '../../data/fixtures/index.ts'
import { applyReviewEvent, isTerminalRunStatus } from './apply-review-event.ts'

function event(eventType: string, payload: Record<string, unknown>): ReviewEventDto {
  return {
    schema: 'worktree-review.event/v1',
    sequence: 1,
    occurred_at: '2026-09-09T16:00:00.000Z',
    attempt_id: 'attempt_1',
    surface: 'web',
    event_type: eventType,
    payload,
  }
}

describe('applyReviewEvent', () => {
  it('marks a stage running and flips awaiting gate to in_progress', () => {
    const base = {
      ...structuredClone(blockedCase),
      runStatus: 'queued' as const,
      gateState: 'awaiting_review' as const,
    }
    const { run, refetch } = applyReviewEvent(
      base,
      event('stage.started', { stage: 'gather-context' }),
    )
    expect(refetch).toBe(false)
    expect(run.runStatus).toBe('running')
    expect(run.gateState).toBe('in_progress')
    expect(run.pipeline.find((stage) => stage.stage === 'gather-context')?.status).toBe('running')
  })

  it('applies stage completion with elapsed time', () => {
    const { run } = applyReviewEvent(
      blockedCase,
      event('stage.completed', { stage: 'publish', elapsed_ms: 900 }),
    )
    const publish = run.pipeline.find((stage) => stage.stage === 'publish')
    expect(publish?.status).toBe('completed')
    expect(publish?.elapsedMs).toBe(900)
  })

  it('ignores events for unknown stages instead of inventing progress', () => {
    const { run, refetch } = applyReviewEvent(
      blockedCase,
      event('stage.started', { stage: 'vibe-check' }),
    )
    expect(refetch).toBe(false)
    expect(run).toBe(blockedCase)
  })

  it('requires a refetch for gate, failure and terminal events', () => {
    for (const type of ['gate.evaluated', 'stage.failed', 'attempt.completed']) {
      expect(applyReviewEvent(blockedCase, event(type, {})).refetch).toBe(true)
    }
  })

  it('updates dimension status only for known dimension ids', () => {
    const started = applyReviewEvent(
      blockedCase,
      event('dimension.started', { dimension_id: 'security' }),
    )
    expect(
      started.run.dimensions.find((dimension) => dimension.dimensionId === 'security')?.status,
    ).toBe('running')

    const unknown = applyReviewEvent(
      blockedCase,
      event('dimension.started', { dimension_id: 'nope' }),
    )
    expect(unknown.run.dimensions).toEqual(blockedCase.dimensions)
  })

  it('leaves provider_call and finding events untouched', () => {
    for (const type of ['provider_call.completed', 'finding.verified', 'coverage.recorded']) {
      const { run, refetch } = applyReviewEvent(blockedCase, event(type, {}))
      expect(run).toBe(blockedCase)
      expect(refetch).toBe(false)
    }
  })
})

describe('isTerminalRunStatus', () => {
  it('classifies terminal and non-terminal states', () => {
    expect(isTerminalRunStatus('completed')).toBe(true)
    expect(isTerminalRunStatus('failed')).toBe(true)
    expect(isTerminalRunStatus('interrupted')).toBe(true)
    expect(isTerminalRunStatus('running')).toBe(false)
    expect(isTerminalRunStatus('queued')).toBe(false)
  })
})
