/**
 * Audit Log page (P3 §9.2): capability honesty (no fabricated data in
 * local/demo mode), mandatory repository scope, keyset pagination, and
 * read-only rendering of sanitized events.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { DataSourceContext } from '../app/data-source.ts'
import type { AuditEventPageView, AuthSessionView } from '../domain/audit.ts'
import type { ReviewDataSource } from '../data/sources/review-data-source.ts'
import { stubMatchMedia } from '../test/match-media.ts'
import { AuditLogPage } from './AuditLogPage.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

const OAUTH_SESSION: AuthSessionView = {
  mode: 'github-oauth',
  authenticated: true,
  actorId: 42,
  actorLogin: 'octocat',
  expiresAt: '2026-09-16T13:00:00+00:00',
  csrfToken: 'session-csrf',
  capabilities: { bypass: true, audit: true },
}

const UNAUTHENTICATED_OAUTH: AuthSessionView = { ...OAUTH_SESSION, authenticated: false }

function auditSource(overrides: Partial<ReviewDataSource>): ReviewDataSource {
  return {
    kind: 'live',
    environmentBadge: null,
    getOverview: () => Promise.reject(new Error('not used')),
    getReviewRun: () => Promise.reject(new Error('not used')),
    listCases: () => Promise.resolve([]),
    getCase: () => Promise.reject(new Error('not used')),
    ...overrides,
  }
}

function renderPage(source: ReviewDataSource) {
  return render(
    <DataSourceContext.Provider
        value={{ source, overview: null, cases: [], loading: false, error: null, authSession: null }}
      >
      <MemoryRouter>
        <AuditLogPage />
      </MemoryRouter>
    </DataSourceContext.Provider>,
  )
}

function auditPage(events: number, nextCursor: string | null = null): AuditEventPageView {
  return {
    events: Array.from({ length: events }, (_, index) => ({
      eventId: 100 - index,
      eventType: index % 2 === 0 ? 'bypass_authorized' : 'check_sync_queued',
      occurredAt: '2026-09-16T12:00:00+00:00',
      installationId: 7,
      repository: 'octo/example',
      pullRequestNumber: 42,
      attemptId: 'attempt-abc-123',
      actorId: 42,
      actorLogin: 'octocat',
      payload: { finding_fingerprint: 'fp-1' },
    })),
    nextCursor,
  }
}

describe('AuditLogPage', () => {
  it('states the missing capability instead of fabricating data (demo/local)', () => {
    renderPage(auditSource({}))
    expect(screen.getByText(/no platform audit capability/i)).toBeInTheDocument()
  })

  it('requires sign-in when the deployment is in oauth mode without a session', async () => {
    renderPage(
      auditSource({
        getAuthSession: () => Promise.resolve(UNAUTHENTICATED_OAUTH),
        listAuditEvents: () => Promise.resolve(auditPage(0)),
      }),
    )
    expect(await screen.findByText('Sign in required')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in with GitHub' })).toHaveAttribute(
      'href',
      '/api/v1/auth/github/start',
    )
  })

  it('never queries without a repository and paginates with cursors', async () => {
    const queries: Array<{ repository: string; cursor: string | null }> = []
    const source = auditSource({
      getAuthSession: () => Promise.resolve(OAUTH_SESSION),
      listAuditEvents: (filter, cursor) => {
        queries.push({ repository: filter.repository, cursor })
        return Promise.resolve(auditPage(2, cursor === null ? 'next-1' : null))
      },
    })
    renderPage(source)
    const user = userEvent.setup()

    const query = screen.getByRole('button', { name: 'Query' })
    expect(query).toBeDisabled()

    await user.type(screen.getByPlaceholderText('owner/repository'), 'octo/example')
    await user.click(query)
    expect(queries).toEqual([{ repository: 'octo/example', cursor: null }])

    const list = await screen.findByRole('list', { name: 'Audit events' })
    expect(within(list).getAllByText('bypass_authorized')).toHaveLength(1)
    expect(within(list).getAllByText(/octo\/example#42/).length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: 'Load more' }))
    expect(queries[1]).toEqual({ repository: 'octo/example', cursor: 'next-1' })
    // Pages accumulate; the list is append-only from the server side.
    await screen.findAllByText('bypass_authorized')
    expect(within(list).getAllByText('bypass_authorized').length).toBeGreaterThan(1)
  })

  it('shows a 403 as an access message, never as data', async () => {
    const { ApiError } = await import('../data/api/review-api-client.ts')
    const source = auditSource({
      getAuthSession: () => Promise.resolve(OAUTH_SESSION),
      listAuditEvents: () => Promise.reject(new ApiError('forbidden', 'no access', 403)),
    })
    renderPage(source)
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('owner/repository'), 'octo/private')
    await user.click(screen.getByRole('button', { name: 'Query' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/do not have read access/i)
  })
})
