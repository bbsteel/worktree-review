import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '../components/ui/badge.tsx'
import { Button } from '../components/ui/button.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { useDataSource } from '../app/data-source.ts'
import type { AuditEventFilter, AuditEventView, AuthSessionView } from '../domain/audit.ts'
import { ApiError } from '../data/api/review-api-client.ts'
import { formatTimestamp } from '../features/review-detail/formatting.ts'
import { shortenFingerprint } from '../features/review-detail/formatting.ts'
import { useI18n } from '../i18n.tsx'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'

const EVENT_TYPE_OPTIONS = [
  'attempt_authoritative',
  'standing_decision_published',
  'standing_decision_invalidated',
  'retry_authorized',
  'retry_denied',
  'bypass_authorized',
  'bypass_denied',
  'bypass_invalidated',
  'gate_transition',
  'check_sync_queued',
  'check_sync_published',
  'check_sync_failed',
  'check_sync_superseded',
  'authorization_revoked',
] as const

function eventTone(eventType: string): 'blocked' | 'passed' | 'warning' | 'neutral' {
  if (eventType.endsWith('_denied') || eventType.endsWith('_failed')) return 'blocked'
  if (eventType === 'bypass_authorized' || eventType === 'gate_transition') return 'warning'
  if (eventType.endsWith('_published') || eventType === 'retry_authorized') return 'passed'
  return 'neutral'
}

function AuditEventRow({ event }: { event: AuditEventView }) {
  const { t } = useI18n()
  return (
    <li className="rounded-md border border-border bg-surface px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-meta text-text-secondary tabular-nums">
          {formatTimestamp(event.occurredAt)}
        </span>
        <Badge tone={eventTone(event.eventType)} label={event.eventType} />
        <span className="text-sm text-text-primary">
          {event.actorLogin ?? t('platform')}
        </span>
        <span className="font-mono text-meta text-text-secondary">
          {event.repository}#{event.pullRequestNumber}
        </span>
        {event.attemptId !== null ? (
          <Link
            to={`/reviews/${encodeURIComponent(event.attemptId)}`}
            className="font-mono text-meta text-action-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            {shortenFingerprint(event.attemptId)}
          </Link>
        ) : null}
      </div>
      {Object.keys(event.payload).length > 0 ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-meta text-text-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
            {t('Safe payload')}
          </summary>
          <pre className="mt-1 overflow-x-auto rounded-md bg-background p-2 text-meta text-text-secondary">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </details>
      ) : null}
    </li>
  )
}

/**
 * Platform Audit Log (P3 §9.2): a compact, read-only, developer-tool-style
 * timeline. The repository scope is mandatory — the page never issues an
 * unscoped "list every installation" query. Local/demo deployments have no
 * platform audit capability and say so instead of fabricating data.
 */
export function AuditLogPage() {
  const { t } = useI18n()
  const { source, overview } = useDataSource()
  const [session, setSession] = useState<AuthSessionView | null>(null)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const [repository, setRepository] = useState('')
  const [eventType, setEventType] = useState('')
  const [events, setEvents] = useState<AuditEventView[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [queryError, setQueryError] = useState<string | null>(null)

  const auditSupported = source.listAuditEvents !== undefined

  useEffect(() => {
    if (source.getAuthSession === undefined) {
      setSession({
        mode: 'local',
        authenticated: false,
        actorId: null,
        actorLogin: null,
        expiresAt: null,
        csrfToken: null,
        capabilities: { bypass: false, audit: false },
      })
      return
    }
    let cancelled = false
    source
      .getAuthSession()
      .then((value) => {
        if (!cancelled) setSession(value)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setSessionError(caught instanceof Error ? caught.message : 'session probe failed')
        }
      })
    return () => {
      cancelled = true
    }
  }, [source])

  const repositoryOptions = useMemo(() => {
    const names = new Set<string>()
    for (const run of [...(overview?.attention ?? []), ...(overview?.recent ?? [])]) {
      if (run.source.kind === 'github-pull-request') {
        names.add(run.source.repositoryFullName)
      }
    }
    return [...names]
  }, [overview])

  const load = useCallback(
    async (cursor: string | null) => {
      if (source.listAuditEvents === undefined || repository === '') return
      setLoading(true)
      setQueryError(null)
      const filter: AuditEventFilter = {
        repository,
        ...(eventType === '' ? {} : { eventType }),
      }
      try {
        const page = await source.listAuditEvents(filter, cursor)
        setEvents((previous) => (cursor === null ? page.events : [...previous, ...page.events]))
        setNextCursor(page.nextCursor)
      } catch (caught: unknown) {
        if (caught instanceof ApiError && caught.httpStatus === 403) {
          setQueryError(t('You do not have read access to this repository’s audit log.'))
        } else {
          setQueryError(
            t('Audit log query failed: {message}', {
              message: caught instanceof Error ? caught.message : 'unknown error',
            }),
          )
        }
      } finally {
        setLoading(false)
      }
    },
    [source, repository, eventType, t],
  )

  if (!auditSupported) {
    return (
      <div className="p-4">
        <EmptyState
          title={t('Audit Log')}
          description={t(
            'This deployment has no platform audit capability. Audit events exist only on the authorized GitHub runtime.',
          )}
        />
      </div>
    )
  }

  if (session !== null && session.mode === 'github-oauth' && !session.authenticated) {
    return (
      <div className="p-4">
        <EmptyState
          title={t('Sign in required')}
          description={t('The audit log requires a verified GitHub session.')}
        />
        <div className="mt-3 text-center">
          <a
            href="/api/v1/auth/github/start"
            className="text-sm text-action-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            {t('Sign in with GitHub')}
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <header>
        <h1 className="text-lg font-semibold text-text-primary">{t('Audit Log')}</h1>
        <p className="mt-1 text-sm text-text-secondary">
          {t(
            'Append-only platform decisions. Events are written by the server, never editable, and payloads are sanitized before persistence.',
          )}
        </p>
      </header>

      {sessionError !== null ? (
        <p role="alert" className="text-sm text-status-blocked">
          {t('Session probe failed: {message}', { message: sessionError })}
        </p>
      ) : null}

      <div
        role="group"
        aria-label={t('Audit filters')}
        className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3 sm:flex-row"
      >
        <label className="flex flex-1 flex-col gap-1 text-meta text-text-secondary">
          {t('Repository (required)')}
          {repositoryOptions.length > 0 ? (
            <select
              value={repository}
              onChange={(event) => {
                setRepository(event.target.value)
                setEvents([])
                setNextCursor(null)
              }}
              className={FIELD_CLASS}
            >
              <option value="">{t('Select a repository')}</option>
              {repositoryOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={repository}
              onChange={(event) => {
                setRepository(event.target.value)
                setEvents([])
                setNextCursor(null)
              }}
              placeholder="owner/repository"
              className={FIELD_CLASS}
            />
          )}
        </label>
        <label className="flex flex-1 flex-col gap-1 text-meta text-text-secondary">
          {t('Event type')}
          <select
            value={eventType}
            onChange={(event) => {
              setEventType(event.target.value)
              setEvents([])
              setNextCursor(null)
            }}
            className={FIELD_CLASS}
          >
            <option value="">{t('All event types')}</option>
            {EVENT_TYPE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <Button
            variant="primary"
            size="sm"
            disabled={repository === '' || loading}
            onClick={() => void load(null)}
          >
            {loading ? t('Loading…') : t('Query')}
          </Button>
        </div>
      </div>

      {queryError !== null ? (
        <div className="flex items-center gap-2">
          <p role="alert" className="text-sm text-status-blocked">
            {queryError}
          </p>
          <Button variant="secondary" size="sm" onClick={() => void load(null)}>
            {t('Retry')}
          </Button>
        </div>
      ) : null}

      {events.length === 0 && !loading && queryError === null ? (
        <EmptyState
          title={repository === '' ? t('Choose a repository') : t('No audit events')}
          description={
            repository === ''
              ? t('Audit queries are always scoped to one repository you can read.')
              : t('No events match the current filters.')
          }
        />
      ) : (
        <ul aria-label={t('Audit events')} className="flex flex-col gap-1">
          {events.map((event) => (
            <AuditEventRow key={event.eventId} event={event} />
          ))}
        </ul>
      )}

      {nextCursor !== null ? (
        <div>
          <Button
            variant="secondary"
            size="sm"
            disabled={loading}
            onClick={() => void load(nextCursor)}
          >
            {loading ? t('Loading…') : t('Load more')}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
