/**
 * Review event SSE session (design 16.5).
 *
 * - Events are validated against worktree-review.event/v1 and deduplicated
 *   by sequence; out-of-order or repeated deliveries are ignored.
 * - On disconnect the session reconnects with `since=<lastSequence>` so the
 *   replay/subscribe handoff cannot drop events; duplicates are deduped.
 * - `attempt.completed` closes the stream; a failed stream reports a visible
 *   state instead of silently hanging.
 * - Slow-client disconnects are handled by reconnecting from the last known
 *   sequence, matching the server contract.
 */
import type { ReviewEventDto } from '../api/dto.ts'
import { DtoValidationError } from '../api/map-dto.ts'

export const REVIEW_EVENT_SCHEMA = 'worktree-review.event/v1'

export type ReviewEventStreamState =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'closed'
  | 'failed'

/** Minimal EventSource surface so tests can inject a fake. */
export interface EventSourceLike {
  onmessage: ((event: { data: string; lastEventId?: string }) => void) | null
  onerror: (() => void) | null
  close(): void
}

export interface ReviewEventStreamOptions {
  attemptId: string
  /** Resume after this sequence; 0 means replay from the start. */
  sinceSequence?: number
  onEvent: (event: ReviewEventDto) => void
  onStateChange?: (state: ReviewEventStreamState) => void
  onInvalidEvent?: (error: DtoValidationError) => void
  baseUrl?: string
  eventSourceFactory?: (url: string) => EventSourceLike
  /** Reconnect backoff in ms; attempts stop after maxReconnects. */
  reconnectDelaysMs?: number[]
}

export interface ReviewEventStream {
  readonly state: ReviewEventStreamState
  readonly lastSequence: number
  close(): void
}

export function parseReviewEvent(data: string): ReviewEventDto {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    throw new DtoValidationError('event', 'not valid JSON')
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new DtoValidationError('event', 'expected an object')
  }
  const event = parsed as Record<string, unknown>
  if (event.schema !== REVIEW_EVENT_SCHEMA) {
    throw new DtoValidationError('event.schema', `unexpected schema "${String(event.schema)}"`)
  }
  if (typeof event.sequence !== 'number' || !Number.isInteger(event.sequence)) {
    throw new DtoValidationError('event.sequence', 'expected an integer')
  }
  if (typeof event.event_type !== 'string' || event.event_type === '') {
    throw new DtoValidationError('event.event_type', 'expected a non-empty string')
  }
  if (typeof event.attempt_id !== 'string') {
    throw new DtoValidationError('event.attempt_id', 'expected a string')
  }
  return {
    schema: REVIEW_EVENT_SCHEMA,
    sequence: event.sequence,
    occurred_at: typeof event.occurred_at === 'string' ? event.occurred_at : '',
    attempt_id: event.attempt_id,
    surface: typeof event.surface === 'string' ? event.surface : '',
    event_type: event.event_type,
    payload:
      typeof event.payload === 'object' && event.payload !== null
        ? (event.payload as Record<string, unknown>)
        : {},
  }
}

export function openReviewEventStream(options: ReviewEventStreamOptions): ReviewEventStream {
  const {
    attemptId,
    onEvent,
    onStateChange,
    onInvalidEvent,
    baseUrl = '/api/v1',
    eventSourceFactory = (url) => new EventSource(url) as EventSourceLike,
    reconnectDelaysMs = [1_000, 2_000, 5_000, 10_000],
  } = options

  let state: ReviewEventStreamState = 'connecting'
  let lastSequence = options.sinceSequence ?? 0
  let reconnectAttempt = 0
  let source: EventSourceLike | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let closedByCaller = false

  function setState(next: ReviewEventStreamState) {
    state = next
    onStateChange?.(next)
  }

  function url(): string {
    const since = lastSequence > 0 ? `?since=${lastSequence}` : ''
    return `${baseUrl}/reviews/${encodeURIComponent(attemptId)}/events${since}`
  }

  function handleMessage(message: { data: string; lastEventId?: string }) {
    let event: ReviewEventDto
    try {
      event = parseReviewEvent(message.data)
    } catch (error) {
      if (error instanceof DtoValidationError) {
        onInvalidEvent?.(error)
      }
      return
    }
    if (event.attempt_id !== attemptId) {
      return
    }
    if (event.sequence <= lastSequence) {
      return
    }
    // A valid new event proves the connection is healthy.
    reconnectAttempt = 0
    if (state !== 'live' && state !== 'closed') {
      setState('live')
    }
    lastSequence = event.sequence
    onEvent(event)
    if (event.event_type === 'attempt.completed') {
      const current = source
      source = null
      current?.close()
      setState('closed')
    }
  }

  function handleError() {
    if (closedByCaller || state === 'closed') {
      return
    }
    const current = source
    source = null
    current?.close()
    if (reconnectAttempt >= reconnectDelaysMs.length) {
      setState('failed')
      return
    }
    const delay = reconnectDelaysMs[reconnectAttempt] ?? 10_000
    reconnectAttempt += 1
    setState('reconnecting')
    reconnectTimer = setTimeout(connect, delay)
  }

  function connect() {
    reconnectTimer = null
    // The transitional state (connecting/reconnecting) is left unchanged until
    // the first valid event flips the session to live.
    source = eventSourceFactory(url())
    source.onmessage = handleMessage
    source.onerror = handleError
  }

  connect()

  return {
    get state() {
      return state
    },
    get lastSequence() {
      return lastSequence
    },
    close() {
      closedByCaller = true
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      const current = source
      source = null
      current?.close()
      if (state !== 'closed') {
        setState('closed')
      }
    },
  }
}
