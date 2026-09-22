/**
 * Session Insight integration helpers (B-203, design 5.5).
 *
 * Deep links use the stable format <baseUrl>#/session/worktree-review/<attempt-id>.
 * The base URL is trusted local configuration — today supplied via the
 * VITE_SESSION_INSIGHT_URL build/env setting, later by the
 * /api/v1/integrations/session-insight endpoint. The link is never guessed
 * from attempt data.
 */

export type SessionInsightConnectionState =
  | 'connected'
  | 'disconnected'
  | 'incompatible'
  | 'disabled'

export const SESSION_INSIGHT_STATE_PRESENTATION: Record<
  SessionInsightConnectionState,
  { label: string; description: string }
> = {
  connected: {
    label: 'Connected',
    description:
      'Session Insight is reachable and supports the Worktree Review reader. Observation is advisory and never affects the Gate.',
  },
  disconnected: {
    label: 'Disconnected',
    description:
      'Session Insight is not running or its address is set only in process environment. Reviews still write a Session Journal for SI to read; the Web UI does not configure the SI address.',
  },
  incompatible: {
    label: 'Version incompatible',
    description:
      'Session Insight is reachable but does not support the required reader/deep-link capability.',
  },
  disabled: {
    label: 'Observation disabled',
    description: 'Session Journal observation is turned off in configuration.',
  },
}

/**
 * Build the stable deep link for one attempt. Returns null when no trusted
 * base URL is configured or the URL is unusable — the caller must show the
 * disabled state instead of inventing an address.
 */
export function sessionInsightDeepLink(
  baseUrl: string | null | undefined,
  attemptId: string,
): string | null {
  if (baseUrl === null || baseUrl === undefined || baseUrl.trim() === '') {
    return null
  }
  let parsed: URL
  try {
    parsed = new URL(baseUrl.trim())
  } catch {
    return null
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return null
  }
  const origin = parsed.origin
  const path = parsed.pathname.replace(/\/+$/, '')
  return `${origin}${path}/#/session/worktree-review/${encodeURIComponent(attemptId)}`
}

/** Trusted Session Insight base URL from build-time configuration. */
export function configuredSessionInsightBaseUrl(): string | null {
  const value = import.meta.env.VITE_SESSION_INSIGHT_URL
  if (typeof value !== 'string' || value.trim() === '') {
    return null
  }
  return value.trim()
}
