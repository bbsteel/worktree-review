import { describe, expect, it } from 'vitest'
import {
  formatCostUsd,
  formatDurationMs,
  formatTimestamp,
  formatTokenCount,
  shortenFingerprint,
  shortenHash,
} from './formatting.ts'

describe('formatDurationMs', () => {
  it('formats minutes and seconds', () => {
    expect(formatDurationMs(138_000)).toBe('2m 18s')
  })

  it('formats sub-minute durations', () => {
    expect(formatDurationMs(4_200)).toBe('4s')
  })

  it('renders null as Unknown, never as zero', () => {
    expect(formatDurationMs(null)).toBe('Unknown')
  })
})

describe('formatCostUsd', () => {
  it('formats known cost with two decimals', () => {
    expect(formatCostUsd(0.42, false)).toBe('$0.42')
  })

  it('renders unknown cost as Unknown even when a number exists', () => {
    expect(formatCostUsd(null, true)).toBe('Unknown')
    expect(formatCostUsd(0.4, true)).toBe('Unknown')
  })
})

describe('formatTokenCount', () => {
  it('groups thousands deterministically', () => {
    expect(formatTokenCount(32_800)).toBe('32,800')
  })

  it('renders null as Unknown', () => {
    expect(formatTokenCount(null)).toBe('Unknown')
  })
})

describe('formatTimestamp', () => {
  it('formats UTC deterministically', () => {
    expect(formatTimestamp('2026-09-09T15:47:18.000Z')).toBe('2026-09-09 15:47:18 UTC')
  })

  it('renders null and invalid input as Unknown', () => {
    expect(formatTimestamp(null)).toBe('Unknown')
    expect(formatTimestamp('not-a-date')).toBe('Unknown')
  })
})

describe('shortenHash', () => {
  it('truncates long values with an ellipsis', () => {
    const value = '3f8c1d92e4b70aa18c6d5e4f0b91c27d8e4a1b2c9f0e7d6a5b4c3d2e1f0a9b8c'
    const short = shortenHash(value)
    expect(short).toBe('3f8c1d92e4b7…0a9b8c')
    expect(short.length).toBeLessThan(value.length)
  })

  it('keeps short values intact', () => {
    expect(shortenHash('abc123')).toBe('abc123')
  })
})

describe('shortenFingerprint', () => {
  it('keeps the stable id segment', () => {
    expect(shortenFingerprint('fp_9f3c1a2b_webhook_unsigned_fallback')).toBe('fp_9f3c1a2b')
  })

  it('handles fingerprints without prefix', () => {
    expect(shortenFingerprint('9f3c1a2b_extra')).toBe('fp_9f3c1a2b')
  })
})
