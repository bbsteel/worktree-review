import { describe, expect, it } from 'vitest'
import {
  SESSION_INSIGHT_STATE_PRESENTATION,
  sessionInsightDeepLink,
  type SessionInsightConnectionState,
} from './session-insight.ts'

describe('sessionInsightDeepLink', () => {
  it('builds the stable deep link format', () => {
    expect(sessionInsightDeepLink('http://127.0.0.1:45615', 'attempt_01J')).toBe(
      'http://127.0.0.1:45615/#/session/worktree-review/attempt_01J',
    )
  })

  it('keeps a configured base path and trims trailing slashes', () => {
    expect(sessionInsightDeepLink('http://127.0.0.1:8080/si/', 'attempt_x')).toBe(
      'http://127.0.0.1:8080/si/#/session/worktree-review/attempt_x',
    )
  })

  it('URL-encodes attempt ids', () => {
    expect(sessionInsightDeepLink('http://127.0.0.1:1', 'attempt a/b')).toBe(
      'http://127.0.0.1:1/#/session/worktree-review/attempt%20a%2Fb',
    )
  })

  it('returns null when no address is configured', () => {
    expect(sessionInsightDeepLink(null, 'attempt_x')).toBeNull()
    expect(sessionInsightDeepLink(undefined, 'attempt_x')).toBeNull()
    expect(sessionInsightDeepLink('   ', 'attempt_x')).toBeNull()
  })

  it('refuses non-http and malformed addresses', () => {
    expect(sessionInsightDeepLink('ftp://example.com', 'attempt_x')).toBeNull()
    expect(sessionInsightDeepLink('not a url', 'attempt_x')).toBeNull()
    expect(sessionInsightDeepLink('javascript:alert(1)', 'attempt_x')).toBeNull()
  })
})

describe('SESSION_INSIGHT_STATE_PRESENTATION', () => {
  it('covers all four states with distinct labels', () => {
    const states: SessionInsightConnectionState[] = [
      'connected',
      'disconnected',
      'incompatible',
      'disabled',
    ]
    const labels = states.map((state) => SESSION_INSIGHT_STATE_PRESENTATION[state].label)
    expect(new Set(labels).size).toBe(4)
    for (const state of states) {
      expect(SESSION_INSIGHT_STATE_PRESENTATION[state].description).toBeTruthy()
    }
  })

  it('states that observation never affects the gate', () => {
    expect(SESSION_INSIGHT_STATE_PRESENTATION.connected.description).toMatch(/never affects the Gate/i)
  })
})
