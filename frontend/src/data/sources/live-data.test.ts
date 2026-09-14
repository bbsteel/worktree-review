import { afterEach, describe, expect, it, vi } from 'vitest'
import { blockedCase } from '../fixtures/index.ts'
import { ReviewNotFoundError } from './review-data-source.ts'
import type { EventSourceLike } from './review-events.ts'
import { openReviewEventStream, parseReviewEvent } from './review-events.ts'
import { LiveReviewDataSource } from './live-review-data-source.ts'
import { IdempotencyConflictError, ReviewApiClient } from '../api/review-api-client.ts'
import { runToDto } from '../api/dto-testing.ts'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('LiveReviewDataSource', () => {
  it('fetches and maps a review run from /api/v1', async () => {
    const fetchFn = vi.fn<typeof fetch>(async (input) => {
      expect(String(input)).toBe('/api/v1/reviews/attempt_01JY8R7F2W')
      return jsonResponse(200, runToDto(blockedCase))
    })
    const source = new LiveReviewDataSource({ fetchFn })

    const run = await source.getReviewRun('attempt_01JY8R7F2W')
    expect(run).toEqual(blockedCase)
  })

  it('serves pipeline snapshots locally even in live mode', async () => {
    const fetchFn = vi.fn<typeof fetch>()
    const source = new LiveReviewDataSource({ fetchFn })

    const cases = await source.listCases()
    expect(cases.length).toBeGreaterThan(0)
    const first = cases[0]
    expect(first).toBeDefined()
    if (first) {
      const run = await source.getReviewRun(first.attemptId)
      expect(run.attemptId).toBe(first.attemptId)
    }
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('maps a 404 on a review to ReviewNotFoundError', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () =>
      jsonResponse(404, { error: { code: 'not_found', message: 'unknown attempt' } }),
    )
    const source = new LiveReviewDataSource({ fetchFn })

    await expect(source.getReviewRun('attempt_missing')).rejects.toBeInstanceOf(
      ReviewNotFoundError,
    )
  })

  it('maps a stable error code for other failures', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () =>
      jsonResponse(500, { error: { code: 'store_unavailable', message: 'SQLite is locked' } }),
    )
    const source = new LiveReviewDataSource({ fetchFn })

    await expect(source.getOverview()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'store_unavailable',
    })
  })
})

describe('ReviewApiClient mutations', () => {
  it('sends Idempotency-Key and CSRF headers on create', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () =>
      jsonResponse(202, { attempt_id: 'attempt_new' }),
    )
    const client = new ReviewApiClient({ fetchFn, csrfToken: 'csrf-token-value' })

    const response = await client.createReview(
      {
        repository_id: 'repo_1',
        source: { kind: 'local-worktree' },
        review_policy_id: 'rp_1',
        compute_policy_id: 'cp_1',
      },
      'idem-123',
    )

    expect(response.attempt_id).toBe('attempt_new')
    const init = fetchFn.mock.calls[0]?.[1]
    const headers = new Headers(init?.headers)
    expect(headers.get('Idempotency-Key')).toBe('idem-123')
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token-value')
  })

  it('maps idempotency conflicts to a stable error', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () =>
      jsonResponse(409, {
        error: { code: 'idempotency_conflict', message: 'Same key, different request.' },
      }),
    )
    const client = new ReviewApiClient({ fetchFn, csrfToken: 'csrf-token-value' })

    await expect(
      client.createReview(
        {
          repository_id: 'repo_1',
          source: { kind: 'local-worktree' },
          review_policy_id: 'rp_1',
          compute_policy_id: 'cp_1',
        },
        'idem-123',
      ),
    ).rejects.toBeInstanceOf(IdempotencyConflictError)
  })

  it('maps network failures to network_unreachable', async () => {
    const fetchFn = vi.fn<typeof fetch>(async () => {
      throw new TypeError('Failed to fetch')
    })
    const client = new ReviewApiClient({ fetchFn })

    await expect(client.getOverview()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'network_unreachable',
    })
  })

  it('never leaks secret values from profile payloads', async () => {
    const profile = {
      profile_id: 'pp_1',
      name: 'openai-production',
      provider: 'openai',
      endpoint: null,
      local_cli_adapter: null,
      local_cli_command: null,
      adapter_label: null,
      credential_reference: '${OPENAI_API_KEY}',
      credential_state: 'configured',
      last_used_at: null,
      health: { profile_name: 'openai-production', status: 'not_tested', observed_at: null },
      referenced_by_history: false,
      is_default: true,
    }
    const fetchFn = vi.fn<typeof fetch>(async () => jsonResponse(200, [profile]))
    const client = new ReviewApiClient({ fetchFn })

    const profiles = await client.listProviderProfiles()
    expect(profiles[0]?.credential_reference).toBe('${OPENAI_API_KEY}')
    expect(JSON.stringify(profiles)).not.toContain('sk-')
  })
})

class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = []

  readonly url: string
  onmessage: ((event: { data: string; lastEventId?: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  emit(event: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }

  fail() {
    this.onerror?.()
  }

  close() {
    this.closed = true
  }
}

function eventPayload(sequence: number, eventType: string, attemptId = 'attempt_1') {
  return {
    schema: 'worktree-review.event/v1',
    sequence,
    occurred_at: '2026-09-09T16:00:00.000Z',
    attempt_id: attemptId,
    surface: 'web',
    event_type: eventType,
    payload: {},
  }
}

describe('openReviewEventStream', () => {
  afterEach(() => {
    FakeEventSource.instances = []
  })

  it('delivers events in order and dedupes repeated sequences', () => {
    const received: number[] = []
    const stream = openReviewEventStream({
      attemptId: 'attempt_1',
      onEvent: (event) => {
        received.push(event.sequence)
      },
      eventSourceFactory: (url) => new FakeEventSource(url),
    })

    const source = FakeEventSource.instances[0]
    source?.emit(eventPayload(1, 'attempt.created'))
    source?.emit(eventPayload(2, 'stage.started'))
    source?.emit(eventPayload(2, 'stage.started')) // duplicate delivery
    source?.emit(eventPayload(1, 'attempt.created')) // replay overlap

    expect(received).toEqual([1, 2])
    expect(stream.state).toBe('live')
    expect(stream.lastSequence).toBe(2)
    stream.close()
  })

  it('ignores events for other attempts and malformed payloads', () => {
    const received: number[] = []
    const invalid: string[] = []
    const stream = openReviewEventStream({
      attemptId: 'attempt_1',
      onEvent: (event) => {
        received.push(event.sequence)
      },
      onInvalidEvent: (error) => {
        invalid.push(error.message)
      },
      eventSourceFactory: (url) => new FakeEventSource(url),
    })

    const source = FakeEventSource.instances[0]
    source?.emit(eventPayload(1, 'attempt.created', 'attempt_OTHER'))
    source?.onmessage?.({ data: 'not-json' })
    source?.emit({ schema: 'other.schema/v9', sequence: 9 })
    source?.emit(eventPayload(2, 'stage.started'))

    expect(received).toEqual([2])
    expect(invalid).toHaveLength(2)
    stream.close()
  })

  it('reconnects with the last sequence after a disconnect', async () => {
    vi.useFakeTimers()
    try {
      const states: string[] = []
      openReviewEventStream({
        attemptId: 'attempt_1',
        onEvent: () => undefined,
        onStateChange: (state) => {
          states.push(state)
        },
        eventSourceFactory: (url) => new FakeEventSource(url),
        reconnectDelaysMs: [100, 200],
      })

      const first = FakeEventSource.instances[0]
      first?.emit(eventPayload(7, 'stage.started'))
      first?.fail()
      expect(states).toContain('reconnecting')

      await vi.advanceTimersByTimeAsync(100)
      expect(FakeEventSource.instances).toHaveLength(2)
      expect(FakeEventSource.instances[1]?.url).toContain('since=7')
    } finally {
      vi.useRealTimers()
    }
  })

  it('fails visibly after exhausting reconnect attempts', async () => {
    vi.useFakeTimers()
    try {
      const states: string[] = []
      openReviewEventStream({
        attemptId: 'attempt_1',
        onEvent: () => undefined,
        onStateChange: (state) => {
          states.push(state)
        },
        eventSourceFactory: (url) => new FakeEventSource(url),
        reconnectDelaysMs: [10],
      })

      FakeEventSource.instances[0]?.fail()
      await vi.advanceTimersByTimeAsync(10)
      FakeEventSource.instances[1]?.fail()
      expect(states[states.length - 1]).toBe('failed')
    } finally {
      vi.useRealTimers()
    }
  })

  it('closes the stream on attempt.failed instead of reconnecting forever', () => {
    const stream = openReviewEventStream({
      attemptId: 'attempt_1',
      onEvent: () => undefined,
      eventSourceFactory: (url) => new FakeEventSource(url),
    })

    const source = FakeEventSource.instances[0]
    source?.emit(eventPayload(1, 'attempt.created'))
    source?.emit(eventPayload(2, 'attempt.failed'))

    expect(stream.state).toBe('closed')
    expect(source?.closed).toBe(true)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('closes the stream on attempt.completed', () => {
    const states: string[] = []
    const stream = openReviewEventStream({
      attemptId: 'attempt_1',
      onEvent: () => undefined,
      onStateChange: (state) => {
        states.push(state)
      },
      eventSourceFactory: (url) => new FakeEventSource(url),
    })

    const source = FakeEventSource.instances[0]
    source?.emit(eventPayload(1, 'attempt.created'))
    source?.emit(eventPayload(2, 'attempt.completed'))

    expect(stream.state).toBe('closed')
    expect(source?.closed).toBe(true)
    expect(states[states.length - 1]).toBe('closed')
  })

  it('parseReviewEvent rejects a wrong schema version', () => {
    expect(() => parseReviewEvent(JSON.stringify({ schema: 'worktree-review.event/v2' }))).toThrow(
      /schema/,
    )
  })
})
