import { describe, expect, it } from 'vitest'
import { blockedCase, errorMergeConflictCase, passedCase } from '../fixtures/index.ts'
import { buildOverview } from '../fixtures/overview.ts'
import { runToDto, overviewToDto } from './dto-testing.ts'
import {
  DtoValidationError,
  mapOverviewDto,
  mapReviewRunDto,
} from './map-dto.ts'

describe('mapReviewRunDto', () => {
  it('round-trips all three frozen cases without loss', () => {
    for (const run of [passedCase, blockedCase, errorMergeConflictCase]) {
      const mapped = mapReviewRunDto(runToDto(run))
      expect(mapped).toEqual(run)
    }
  })

  it('rejects an unknown gate state instead of guessing', () => {
    const dto = runToDto(blockedCase)
    dto.gate_state = 'sorta_blocked'
    expect(() => mapReviewRunDto(dto)).toThrow(DtoValidationError)
  })

  it('rejects an unknown authority value', () => {
    const dto = runToDto(blockedCase)
    dto.authority = 'mostly_authoritative'
    expect(() => mapReviewRunDto(dto)).toThrow(/authority/)
  })

  it('rejects an unknown severity inside a finding', () => {
    const dto = runToDto(blockedCase)
    const finding = dto.findings[0]
    expect(finding).toBeDefined()
    if (finding) {
      finding.severity = 'catastrophic'
    }
    expect(() => mapReviewRunDto(dto)).toThrow(/severity/)
  })

  it('rejects an unknown pipeline stage name', () => {
    const dto = runToDto(blockedCase)
    const stage = dto.pipeline[0]
    if (stage) {
      stage.stage = 'vibe-check'
    }
    expect(() => mapReviewRunDto(dto)).toThrow(/pipeline\[0\]\.stage/)
  })

  it('rejects missing objects and wrong scalar types', () => {
    expect(() => mapReviewRunDto(null)).toThrow(DtoValidationError)
    expect(() => mapReviewRunDto([])).toThrow(DtoValidationError)

    const dto = runToDto(blockedCase)
    const broken = { ...dto, summary: { ...dto.summary, finding_count: 'three' } }
    expect(() => mapReviewRunDto(broken)).toThrow(/finding_count/)
  })

  it('keeps unknown-cost semantics intact', () => {
    const dto = runToDto(errorMergeConflictCase)
    const mapped = mapReviewRunDto(dto)
    expect(mapped.usage.costUnknown).toBe(true)
    expect(mapped.usage.actualCostUsd).toBeNull()
  })
})

describe('mapOverviewDto', () => {
  it('round-trips the overview fixture', () => {
    const overview = buildOverview()
    const mapped = mapOverviewDto(overviewToDto(overview))
    expect(mapped).toEqual(overview)
  })

  it('rejects an unknown session insight state', () => {
    const dto = overviewToDto(buildOverview())
    dto.session_insight.state = 'telepathic'
    expect(() => mapOverviewDto(dto)).toThrow(/session_insight\.state/)
  })
})
