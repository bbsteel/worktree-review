/**
 * Deterministic display formatting for Review Detail.
 * Unknown values render as "Unknown", never as zero or blank (design 22.4).
 */

const tokenFormatter = new Intl.NumberFormat('en-US')

export function formatDurationMs(durationMs: number | null): string {
  if (durationMs === null) {
    return 'Unknown'
  }
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) {
    return `${seconds}s`
  }
  return `${minutes}m ${seconds}s`
}

export function formatCostUsd(costUsd: number | null, costUnknown: boolean): string {
  if (costUnknown || costUsd === null) {
    return 'Unknown'
  }
  return `$${costUsd.toFixed(2)}`
}

export function formatTokenCount(tokens: number | null): string {
  if (tokens === null) {
    return 'Unknown'
  }
  return tokenFormatter.format(tokens)
}

/** UTC formatting keeps fixtures and screenshots deterministic across machines. */
export function formatTimestamp(iso: string | null): string {
  if (iso === null) {
    return 'Unknown'
  }
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return 'Unknown'
  }
  const pad = (value: number) => String(value).padStart(2, '0')
  const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
  const time = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
  return `${day} ${time} UTC`
}

/** Truncate long machine identifiers; the full value stays available via title/copy. */
export function shortenHash(value: string, headLength = 12, tailLength = 6): string {
  if (value.length <= headLength + tailLength + 1) {
    return value
  }
  return `${value.slice(0, headLength)}…${value.slice(-tailLength)}`
}

/** Short fingerprint form used in Finding rows, e.g. fp_9f3c1a2b from fp_9f3c1a2b_webhook_unsigned_fallback. */
export function shortenFingerprint(fingerprint: string): string {
  const withoutPrefix = fingerprint.startsWith('fp_') ? fingerprint.slice(3) : fingerprint
  const firstSegment = withoutPrefix.split('_')[0] ?? withoutPrefix
  return `fp_${firstSegment}`
}
