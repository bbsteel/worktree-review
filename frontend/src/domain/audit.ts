/**
 * P3 authorized-deployment views: authenticated session and the append-only
 * platform audit log (design §4/§8.3). Audit events are read-only; the server
 * sanitizes payloads before persistence, and the UI never renders secrets,
 * source snippets, or raw exception text.
 */

import type { CheckSyncStatus } from './review.ts'

export type AuthSessionMode = 'local' | 'github-oauth'

export interface AuthSessionView {
  mode: AuthSessionMode
  authenticated: boolean
  actorId: number | null
  actorLogin: string | null
  expiresAt: string | null
  /** Session-scoped CSRF token for mutations in the authorized mode. */
  csrfToken: string | null
  capabilities: {
    bypass: boolean
    audit: boolean
  }
}

export interface AuditEventView {
  eventId: number
  eventType: string
  occurredAt: string
  installationId: number
  repository: string
  pullRequestNumber: number
  attemptId: string | null
  actorId: number | null
  actorLogin: string | null
  payload: Record<string, unknown>
}

export interface AuditEventPageView {
  events: AuditEventView[]
  nextCursor: string | null
}

export interface AuditEventFilter {
  /** Mandatory: the server rejects unscoped audit queries. */
  repository: string
  eventType?: string
  attemptId?: string
  pullRequestNumber?: number
}

/** Result of one accepted per-finding bypass submission (P3 §8.1). */
export interface BypassSubmissionView {
  bypassId: number
  bypassState: string
  standingGateState: string | null
  remainingBlockingCount: number
  standingRevision: number
  checkSyncStatus: CheckSyncStatus
  gateTransitioned: boolean
  replayed: boolean
}
