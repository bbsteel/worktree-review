/**
 * B-105 live wiring: real events drive the Review Detail view while a run is
 * in flight, terminal events refetch the authoritative run, reconnects resume
 * from the last sequence, and terminal runs never open a stream.
 */
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { ReviewEventDto } from '../data/api/dto.ts'
import type { ReviewDataSource } from '../data/sources/review-data-source.ts'
import type {
  ReviewEventStream,
  ReviewEventStreamOptions,
} from '../data/sources/review-events.ts'
import { blockedCase } from '../data/fixtures/index.ts'
import type { ReviewRunView } from '../domain/review.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { ReviewDetailPage } from './ReviewDetailPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

function runningRun(): ReviewRunView {
  const run = structuredClone(blockedCase)
  run.runStatus = 'running'
  run.gateState = 'in_progress'
  run.gate = {
    gateState: 'in_progress',
    blockingFingerprints: [],
    summary: 'Review in progress.',
    requiredCoverageComplete: false,
  }
  run.findings = []
  run.pipeline = run.pipeline.map((stage, index) => ({
    ...stage,
    status: index < 3 ? 'completed' : 'not-started',
    elapsedMs: index < 3 ? 1_000 : null,
    safeError: null,
  }))
  run.dimensions = run.dimensions.map((dimension) => ({
    ...dimension,
    status: 'not-started',
    elapsedMs: null,
    findingCount: 0,
    blockingFindingCount: 0,
  }))
  return run
}

class FakeStream implements ReviewEventStream {
  state = 'live' as const
  lastSequence = 0
  closed = false
  readonly options: ReviewEventStreamOptions

  constructor(options: ReviewEventStreamOptions) {
    this.options = options
    // The fake connects immediately, like a healthy EventSource that already
    // received its first heartbeat.
    this.options.onStateChange?.('live')
  }

  emit(event: Partial<ReviewEventDto> & { sequence: number; event_type: string }) {
    const full: ReviewEventDto = {
      schema: 'worktree-review.event/v1',
      occurred_at: '2026-09-09T16:00:00.000Z',
      attempt_id: this.options.attemptId,
      surface: 'web',
      payload: {},
      ...event,
    }
    // A valid event proves the connection is live, mirroring the real stream.
    this.options.onStateChange?.('live')
    this.options.onEvent(full)
  }

  close() {
    this.closed = true
  }
}

interface Harness {
  source: ReviewDataSource
  streams: FakeStream[]
  getReviewRun: ReturnType<typeof vi.fn>
}

function harness(initialRun: ReviewRunView, afterRefetchRun?: ReviewRunView): Harness {
  const streams: FakeStream[] = []
  let callCount = 0
  const getReviewRun = vi.fn(async () => {
    callCount += 1
    return structuredClone(callCount === 1 ? initialRun : (afterRefetchRun ?? initialRun))
  })
  const source = {
    kind: 'live',
    environmentBadge: null,
    getOverview: async () => {
      throw new Error('unused')
    },
    listCases: async () => [],
    getCase: async () => {
      throw new Error('unused')
    },
    getReviewRun,
  } satisfies ReviewDataSource
  return { source, streams, getReviewRun }
}

function renderDetail(h: Harness) {
  const openEventStream = (options: ReviewEventStreamOptions): ReviewEventStream => {
    const stream = new FakeStream(options)
    h.streams.push(stream)
    return stream
  }
  const router = createMemoryRouter(
    [
      {
        path: '/reviews/:attemptId',
        element: <ReviewDetailPage dataSource={h.source} openEventStream={openEventStream} />,
      },
    ],
    { initialEntries: [`/reviews/${blockedCase.attemptId}`] },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('ReviewDetailPage live wiring', () => {
  it('opens an event stream for a running attempt and applies stage events', async () => {
    const h = harness(runningRun())
    renderDetail(h)

    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })
    expect(h.streams).toHaveLength(1)
    expect(h.streams[0]?.options.sinceSequence).toBe(0)
    expect(await screen.findByText(/Live updates connected/)).toBeInTheDocument()

    const pipelineSection = screen.getByRole('heading', { name: 'Review Pipeline' })
      .parentElement as HTMLElement
    expect(within(pipelineSection).getAllByText('Not started').length).toBeGreaterThan(0)

    act(() => {
      h.streams[0]?.emit({ sequence: 1, event_type: 'stage.started', payload: { stage: 'gather-context' } })
    })
    expect(within(pipelineSection).getByText('Gather Context')).toBeInTheDocument()
    expect(within(pipelineSection).getByText('Running')).toBeInTheDocument()

    act(() => {
      h.streams[0]?.emit({
        sequence: 2,
        event_type: 'stage.completed',
        payload: { stage: 'gather-context', elapsed_ms: 2_400 },
      })
    })
    expect(within(pipelineSection).getByText('Gather Context')).toBeInTheDocument()
    expect(within(pipelineSection).getAllByText('Completed').length).toBe(4)
  })

  it('applies dimension events without touching the finding selection', async () => {
    const h = harness(runningRun())
    const router = renderDetail(h)
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })

    act(() => {
      h.streams[0]?.emit({
        sequence: 1,
        event_type: 'dimension.started',
        payload: { dimension_id: 'security' },
      })
    })

    const dimensionsSection = screen.getByRole('heading', { name: 'Required Dimensions' })
      .parentElement as HTMLElement
    const securityRow = within(dimensionsSection).getByText('security').closest('li')
    expect(securityRow?.textContent).toContain('Running')
    expect(router.state.location.search).toBe('')
  })

  it('refetches the authoritative run on attempt.completed and closes the stream', async () => {
    const h = harness(runningRun(), blockedCase)
    renderDetail(h)
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })
    expect(h.getReviewRun).toHaveBeenCalledTimes(1)

    act(() => {
      h.streams[0]?.emit({ sequence: 9, event_type: 'attempt.completed' })
    })

    // After the refetch the terminal gate is rendered and no new stream opens.
    await waitFor(() => {
      expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0)
    })
    expect(h.getReviewRun).toHaveBeenCalledTimes(2)
    expect(h.streams[0]?.closed).toBe(true)
    expect(h.streams).toHaveLength(1)
  })

  it('shows a reconnecting banner and resumes from the last sequence', async () => {
    let stateListener: ((state: string) => void) | undefined
    const h = harness(runningRun())
    const openEventStream = (options: ReviewEventStreamOptions): ReviewEventStream => {
      stateListener = options.onStateChange as (state: string) => void
      const stream = new FakeStream(options)
      h.streams.push(stream)
      return stream
    }
    const router = createMemoryRouter(
      [
        {
          path: '/reviews/:attemptId',
          element: <ReviewDetailPage dataSource={h.source} openEventStream={openEventStream} />,
        },
      ],
      { initialEntries: [`/reviews/${blockedCase.attemptId}`] },
    )
    render(<RouterProvider router={router} />)
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })

    act(() => {
      h.streams[0]?.emit({ sequence: 5, event_type: 'stage.started', payload: { stage: 'run-dimensions' } })
    })
    act(() => {
      stateListener?.('reconnecting')
    })

    expect(await screen.findByRole('alert')).toHaveTextContent(/reconnecting from.*sequence 5/i)
    expect(router.state.location.pathname).toBe(`/reviews/${blockedCase.attemptId}`)
  })

  it('offers manual reconnect after the stream failed', async () => {
    let stateListener: ((state: string) => void) | undefined
    const h = harness(runningRun())
    const openEventStream = (options: ReviewEventStreamOptions): ReviewEventStream => {
      stateListener = options.onStateChange as (state: string) => void
      const stream = new FakeStream(options)
      h.streams.push(stream)
      return stream
    }
    render(
      <RouterProvider
        router={createMemoryRouter(
          [
            {
              path: '/reviews/:attemptId',
              element: (
                <ReviewDetailPage dataSource={h.source} openEventStream={openEventStream} />
              ),
            },
          ],
          { initialEntries: [`/reviews/${blockedCase.attemptId}`] },
        )}
      />,
    )
    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })

    act(() => {
      h.streams[0]?.emit({ sequence: 3, event_type: 'stage.started', payload: { stage: 'gather-context' } })
      stateListener?.('failed')
    })
    expect(await screen.findByRole('alert')).toHaveTextContent(/Live updates disconnected/)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Reconnect live updates' }))

    expect(h.streams).toHaveLength(2)
    expect(h.streams[1]?.options.sinceSequence).toBe(3)
  })

  it('never opens a stream for a terminal run', async () => {
    const h = harness(blockedCase)
    renderDetail(h)

    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })
    expect(h.streams).toHaveLength(0)
    expect(screen.queryByText(/Live updates connected/)).not.toBeInTheDocument()
  })

  it('keeps local attempts free of standing-decision and bypass UI', async () => {
    const localRun = structuredClone(blockedCase)
    localRun.authority = 'local_non_authoritative'
    localRun.availableActions = {
      ...localRun.availableActions,
      bypass: { visible: false, enabled: false, disabledReason: null },
    }
    const h = harness(localRun)
    renderDetail(h)

    await screen.findByRole('heading', { name: 'acme/payment-service · PR #184' })
    expect(screen.getByText('Local one-shot result')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Bypass' })).not.toBeInTheDocument()
    expect(screen.queryByText(/standing decision is/i)).not.toBeInTheDocument()
  })
})
