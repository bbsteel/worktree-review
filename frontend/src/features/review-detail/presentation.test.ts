import { describe, expect, it } from 'vitest'
import type {
  Authority,
  CoverageCategory,
  EvidenceBand,
  FindingSeverity,
  GateState,
  PipelineStageName,
  PublicationStatus,
  ReviewSourceKind,
  RunStatus,
} from '../../domain/review.ts'
import { PIPELINE_STAGE_ORDER } from '../../domain/review.ts'
import {
  AUTHORITY_PRESENTATION,
  COVERAGE_CATEGORY_PRESENTATION,
  EVIDENCE_BAND_PRESENTATION,
  GATE_PRESENTATION,
  PIPELINE_STAGE_LABEL,
  PUBLICATION_PRESENTATION,
  RUN_STATUS_PRESENTATION,
  SEVERITY_PRESENTATION,
  SOURCE_KIND_LABEL,
} from './presentation.ts'

const ALL_GATES: GateState[] = [
  'awaiting_review',
  'in_progress',
  'passed',
  'passed_with_bypass',
  'blocked',
  'error',
]
const ALL_RUN_STATUSES: RunStatus[] = [
  'queued',
  'preparing',
  'running',
  'completed',
  'failed',
  'interrupted',
]
const ALL_SEVERITIES: FindingSeverity[] = ['critical', 'major', 'minor', 'suggestion']
const ALL_AUTHORITIES: Authority[] = [
  'local_non_authoritative',
  'authoritative',
  'superseded',
  'audit_only',
]
const ALL_PUBLICATION: PublicationStatus[] = [
  'not_applicable',
  'queued',
  'in_progress',
  'published',
  'failed',
]
const ALL_BANDS: EvidenceBand[] = ['supported', 'insufficient']
const ALL_SOURCES: ReviewSourceKind[] = [
  'local-worktree',
  'local-recent-commits',
  'local-committed-ref',
  'github-pull-request',
]
const ALL_COVERAGE: CoverageCategory[] = [
  'reviewed',
  'mandatory-missing',
  'optional-missing',
  'excluded',
  'unreviewable',
]

describe('presentation maps', () => {
  it('cover every frozen enum value', () => {
    for (const gate of ALL_GATES) {
      expect(GATE_PRESENTATION[gate].label).toBeTruthy()
      expect(GATE_PRESENTATION[gate].description).toBeTruthy()
    }
    for (const status of ALL_RUN_STATUSES) {
      expect(RUN_STATUS_PRESENTATION[status].label).toBeTruthy()
    }
    for (const severity of ALL_SEVERITIES) {
      expect(SEVERITY_PRESENTATION[severity].label).toBeTruthy()
    }
    for (const authority of ALL_AUTHORITIES) {
      expect(AUTHORITY_PRESENTATION[authority].label).toBeTruthy()
    }
    for (const publication of ALL_PUBLICATION) {
      expect(PUBLICATION_PRESENTATION[publication].label).toBeTruthy()
    }
    for (const band of ALL_BANDS) {
      expect(EVIDENCE_BAND_PRESENTATION[band].label).toBeTruthy()
    }
    for (const source of ALL_SOURCES) {
      expect(SOURCE_KIND_LABEL[source]).toBeTruthy()
    }
    for (const category of ALL_COVERAGE) {
      expect(COVERAGE_CATEGORY_PRESENTATION[category].label).toBeTruthy()
    }
  })

  it('gives every pipeline stage a label', () => {
    const stages: PipelineStageName[] = [...PIPELINE_STAGE_ORDER]
    expect(stages).toHaveLength(9)
    for (const stage of stages) {
      expect(PIPELINE_STAGE_LABEL[stage]).toBeTruthy()
    }
  })

  it('keeps gate labels distinct so status never relies on color alone', () => {
    const labels = ALL_GATES.map((gate) => GATE_PRESENTATION[gate].label)
    expect(new Set(labels).size).toBe(labels.length)
  })

  it('marks Passed with Bypass as not a clean pass', () => {
    expect(GATE_PRESENTATION.passed_with_bypass.description).toMatch(/not a clean pass/i)
  })

  it('explains that superseded attempts lose gate authority', () => {
    expect(AUTHORITY_PRESENTATION.superseded.description).toMatch(/no longer/i)
  })
})
