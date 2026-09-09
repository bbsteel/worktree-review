/**
 * Pure finding filter logic for the Findings workspace (design 13.5).
 * Filters only change the current view; they never affect the Gate.
 */
import type { EvidenceBand, FindingSeverity, ReviewFindingView } from '../../domain/review.ts'

export interface FindingFilter {
  query: string
  severity: FindingSeverity | 'all'
  dimensionId: string | 'all'
  evidenceBand: EvidenceBand | 'all'
  blockingOnly: boolean
}

export const EMPTY_FINDING_FILTER: FindingFilter = {
  query: '',
  severity: 'all',
  dimensionId: 'all',
  evidenceBand: 'all',
  blockingOnly: false,
}

export function isDefaultFindingFilter(filter: FindingFilter): boolean {
  return (
    filter.query === '' &&
    filter.severity === 'all' &&
    filter.dimensionId === 'all' &&
    filter.evidenceBand === 'all' &&
    !filter.blockingOnly
  )
}

function matchesQuery(finding: ReviewFindingView, query: string): boolean {
  const haystack = [
    finding.fingerprint,
    finding.problemStatement,
    finding.dimensionId,
    ...finding.evidenceSpans.map((span) => span.path),
  ]
    .join('\n')
    .toLowerCase()
  return haystack.includes(query)
}

export function filterFindings(
  findings: ReviewFindingView[],
  filter: FindingFilter,
): ReviewFindingView[] {
  const query = filter.query.trim().toLowerCase()
  return findings.filter((finding) => {
    if (filter.severity !== 'all' && finding.severity !== filter.severity) {
      return false
    }
    if (filter.dimensionId !== 'all' && finding.dimensionId !== filter.dimensionId) {
      return false
    }
    if (filter.evidenceBand !== 'all' && finding.evidenceBand !== filter.evidenceBand) {
      return false
    }
    if (filter.blockingOnly && !finding.blocking) {
      return false
    }
    if (query !== '' && !matchesQuery(finding, query)) {
      return false
    }
    return true
  })
}

/** Read the filter and selection from the URL query (design 13.1/13.5). */
export function readFindingFilter(searchParams: URLSearchParams): FindingFilter {
  const severity = searchParams.get('severity')
  const dimensionId = searchParams.get('dimension')
  const evidenceBand = searchParams.get('band')
  return {
    query: searchParams.get('q') ?? '',
    severity:
      severity === 'critical' || severity === 'major' || severity === 'minor' || severity === 'suggestion'
        ? severity
        : 'all',
    dimensionId: dimensionId ?? 'all',
    evidenceBand: evidenceBand === 'supported' || evidenceBand === 'insufficient' ? evidenceBand : 'all',
    blockingOnly: searchParams.get('blocking') === '1',
  }
}

export function writeFindingFilter(
  searchParams: URLSearchParams,
  filter: FindingFilter,
): URLSearchParams {
  const next = new URLSearchParams(searchParams)
  const setOrDelete = (key: string, value: string, isDefault: boolean) => {
    if (isDefault) {
      next.delete(key)
    } else {
      next.set(key, value)
    }
  }
  setOrDelete('q', filter.query, filter.query.trim() === '')
  setOrDelete('severity', filter.severity, filter.severity === 'all')
  setOrDelete('dimension', filter.dimensionId, filter.dimensionId === 'all')
  setOrDelete('band', filter.evidenceBand, filter.evidenceBand === 'all')
  setOrDelete('blocking', '1', !filter.blockingOnly)
  return next
}

export function writeSelectedFinding(
  searchParams: URLSearchParams,
  fingerprint: string | null,
): URLSearchParams {
  const next = new URLSearchParams(searchParams)
  if (fingerprint === null) {
    next.delete('finding')
  } else {
    next.set('finding', fingerprint)
  }
  return next
}
