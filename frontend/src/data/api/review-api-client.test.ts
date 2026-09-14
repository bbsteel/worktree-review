import { describe, expect, it, vi } from 'vitest'
import { ApiError, ReviewApiClient } from './review-api-client.ts'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ReviewApiClient CSRF bootstrap', () => {
  it('fetches the server-issued token before the first mutation', async () => {
    const seenTokens: string[] = []
    const fetchFn = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input)
      if (url === '/api/v1/csrf-bootstrap') {
        return jsonResponse(200, { csrf_token: 'server-issued-token' })
      }
      const headers = (init?.headers ?? {}) as Record<string, string>
      seenTokens.push(String(headers['X-CSRF-Token']))
      return jsonResponse(201, { repository_id: 'repo_1' })
    })
    const client = new ReviewApiClient({ fetchFn })

    await client.registerRepository({ path: '/repo' })
    await client.registerRepository({ path: '/repo-2' })

    expect(seenTokens).toEqual(['server-issued-token', 'server-issued-token'])
    const bootstrapCalls = fetchFn.mock.calls.filter(
      ([input]) => String(input) === '/api/v1/csrf-bootstrap',
    )
    expect(bootstrapCalls).toHaveLength(1)
  })

  it('refreshes the token and retries once on invalid_csrf_token', async () => {
    const seenTokens: string[] = []
    let bootstrapCount = 0
    const fetchFn = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input)
      if (url === '/api/v1/csrf-bootstrap') {
        bootstrapCount += 1
        return jsonResponse(200, { csrf_token: `token-${bootstrapCount}` })
      }
      const headers = (init?.headers ?? {}) as Record<string, string>
      const token = String(headers['X-CSRF-Token'])
      seenTokens.push(token)
      if (token === 'token-1') {
        return jsonResponse(403, {
          error: { code: 'invalid_csrf_token', message: 'token does not match this server' },
        })
      }
      return jsonResponse(202, { attempt_id: 'attempt_1' })
    })
    const client = new ReviewApiClient({ fetchFn })

    const created = await client.createReview(
      {
        repository_id: 'repo_1',
        source: { kind: 'local-worktree' },
        review_policy_id: 'rp_1',
        compute_policy_id: 'cp_1',
      },
      'idem-1',
    )

    expect(created.attempt_id).toBe('attempt_1')
    expect(seenTokens).toEqual(['token-1', 'token-2'])
    // The retried mutation keeps the same Idempotency-Key.
    const mutationCalls = fetchFn.mock.calls.filter(
      ([input]) => String(input) === '/api/v1/reviews',
    )
    for (const [, init] of mutationCalls) {
      const headers = (init?.headers ?? {}) as Record<string, string>
      expect(headers['Idempotency-Key']).toBe('idem-1')
    }
  })

  it('does not retry a second CSRF rejection', async () => {
    const fetchFn = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === '/api/v1/csrf-bootstrap') {
        return jsonResponse(200, { csrf_token: 'token-x' })
      }
      return jsonResponse(403, {
        error: { code: 'missing_csrf_token', message: 'required' },
      })
    })
    const client = new ReviewApiClient({ fetchFn })

    await expect(client.registerRepository({ path: '/repo' })).rejects
      .toMatchObject({ name: 'ApiError', code: 'missing_csrf_token', httpStatus: 403 })
    const mutationCalls = fetchFn.mock.calls.filter(
      ([input]) => String(input) === '/api/v1/repositories',
    )
    expect(mutationCalls).toHaveLength(2)
  })

  it('surfaces a bootstrap failure instead of sending an unauthenticated mutation', async () => {
    const fetchFn = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === '/api/v1/csrf-bootstrap') {
        return jsonResponse(403, { error: { code: 'forbidden_host', message: 'loopback only' } })
      }
      throw new Error('mutation must not be attempted without a token')
    })
    const client = new ReviewApiClient({ fetchFn })

    await expect(client.registerRepository({ path: '/repo' })).rejects
      .toBeInstanceOf(ApiError)
  })
})
