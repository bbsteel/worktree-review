import { describe, expect, it } from 'vitest'
import { blockedCase } from '../../data/fixtures/index.ts'
import {
  EMPTY_FINDING_FILTER,
  filterFindings,
  isDefaultFindingFilter,
  readFindingFilter,
  writeFindingFilter,
} from './finding-filter.ts'

const findings = blockedCase.findings

describe('filterFindings', () => {
  it('returns all findings for the default filter', () => {
    expect(filterFindings(findings, EMPTY_FINDING_FILTER)).toHaveLength(3)
  })

  it('filters by severity', () => {
    const result = filterFindings(findings, { ...EMPTY_FINDING_FILTER, severity: 'major' })
    expect(result).toHaveLength(1)
    expect(result[0]?.fingerprint).toBe('fp_9f3c1a2b_webhook_unsigned_fallback')
  })

  it('filters by dimension', () => {
    const result = filterFindings(findings, { ...EMPTY_FINDING_FILTER, dimensionId: 'architecture' })
    expect(result).toHaveLength(1)
    expect(result[0]?.dimensionId).toBe('architecture')
  })

  it('filters by evidence band', () => {
    const result = filterFindings(findings, {
      ...EMPTY_FINDING_FILTER,
      evidenceBand: 'insufficient',
    })
    expect(result).toHaveLength(1)
    expect(result[0]?.evidenceBand).toBe('insufficient')
  })

  it('filters blocking only', () => {
    const result = filterFindings(findings, { ...EMPTY_FINDING_FILTER, blockingOnly: true })
    expect(result).toHaveLength(1)
    expect(result[0]?.blocking).toBe(true)
  })

  it('searches problem statement, path and fingerprint', () => {
    expect(
      filterFindings(findings, { ...EMPTY_FINDING_FILTER, query: 'retention' }),
    ).toHaveLength(1)
    expect(
      filterFindings(findings, { ...EMPTY_FINDING_FILTER, query: 'provider.py' }),
    ).toHaveLength(1)
    expect(
      filterFindings(findings, { ...EMPTY_FINDING_FILTER, query: 'fp_b2a90e11' }),
    ).toHaveLength(1)
    expect(filterFindings(findings, { ...EMPTY_FINDING_FILTER, query: 'no-such-text' })).toHaveLength(
      0,
    )
  })
})

describe('filter URL round-trip', () => {
  it('writes and reads the same filter', () => {
    const filter = {
      query: 'verify',
      severity: 'major' as const,
      dimensionId: 'security',
      evidenceBand: 'supported' as const,
      blockingOnly: true,
    }
    const params = writeFindingFilter(new URLSearchParams('tab=findings'), filter)
    expect(params.get('tab')).toBe('findings')
    expect(readFindingFilter(params)).toEqual(filter)
  })

  it('omits default values from the URL', () => {
    const params = writeFindingFilter(new URLSearchParams(), EMPTY_FINDING_FILTER)
    expect(params.toString()).toBe('')
    expect(isDefaultFindingFilter(readFindingFilter(params))).toBe(true)
  })

  it('rejects invalid enum values as all', () => {
    const params = new URLSearchParams('severity=bogus&band=nope')
    const filter = readFindingFilter(params)
    expect(filter.severity).toBe('all')
    expect(filter.evidenceBand).toBe('all')
  })
})
