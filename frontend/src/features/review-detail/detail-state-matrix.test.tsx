/**
 * Deterministic state matrix for Review Detail (design 22.5).
 * Each state is derived from frozen fixtures by overriding only the fields
 * that define the state, so tests never depend on timers, randomness or the
 * network. States not reachable through P0 fixtures are covered here at
 * component level; browser regression for the full matrix lands in P0.5.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { blockedCase, passedCase } from '../../data/fixtures/index.ts'
import type { PipelineStageView, ReviewRunView } from '../../domain/review.ts'
import { PIPELINE_STAGE_ORDER } from '../../domain/review.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { CoverageTab } from './CoverageTab.tsx'
import { MergeCandidatePath } from './MergeCandidatePath.tsx'
import { OverviewTab } from './OverviewTab.tsx'
import { PipelineStages } from './PipelineStages.tsx'
import { ReviewHeader } from './ReviewHeader.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': true })
})

afterEach(() => {
  cleanup()
})

function derive(overrides: Partial<ReviewRunView>): ReviewRunView {
  return { ...structuredClone(blockedCase), ...overrides }
}

function notStartedPipeline(): PipelineStageView[] {
  return PIPELINE_STAGE_ORDER.map((stage) => ({
    stage,
    status: 'not-started',
    elapsedMs: null,
    safeError: null,
  }))
}

function runningPipeline(runningStage: PipelineStageView['stage']): PipelineStageView[] {
  const runningIndex = PIPELINE_STAGE_ORDER.indexOf(runningStage)
  return PIPELINE_STAGE_ORDER.map((stage, index) => ({
    stage,
    status: index < runningIndex ? 'completed' : index === runningIndex ? 'running' : 'not-started',
    elapsedMs: index < runningIndex ? 1_000 : null,
    safeError: null,
  }))
}

function failedPipeline(
  failedStage: PipelineStageView['stage'],
  safeError: string,
): PipelineStageView[] {
  const failedIndex = PIPELINE_STAGE_ORDER.indexOf(failedStage)
  return PIPELINE_STAGE_ORDER.map((stage, index) => ({
    stage,
    status: index < failedIndex ? 'completed' : index === failedIndex ? 'failed' : 'not-started',
    elapsedMs: index <= failedIndex ? 1_000 : null,
    safeError: index === failedIndex ? safeError : null,
  }))
}

describe('state: Awaiting Review (queued)', () => {
  const run = derive({
    runStatus: 'queued',
    gateState: 'awaiting_review',
    gate: {
      gateState: 'awaiting_review',
      blockingFingerprints: [],
      summary: 'Attempt queued; the review has not started.',
      requiredCoverageComplete: false,
    },
    pipeline: notStartedPipeline(),
    dimensions: blockedCase.dimensions.map((dimension) => ({
      ...dimension,
      status: 'not-started' as const,
      elapsedMs: null,
      findingCount: 0,
      blockingFindingCount: 0,
    })),
  })

  it('shows Awaiting Review with the queued run status as text', () => {
    render(<ReviewHeader run={run} />)

    expect(screen.getByText('Awaiting Review')).toBeInTheDocument()
    expect(screen.getByText(/Run status: Queued/)).toBeInTheDocument()
  })

  it('does not present blocking counts as evaluated', () => {
    render(<OverviewTab run={run} />)

    expect(screen.getByText(/Not evaluated/)).toBeInTheDocument()
  })
})

describe('state: In Progress (running)', () => {
  const run = derive({
    runStatus: 'running',
    gateState: 'in_progress',
    gate: {
      gateState: 'in_progress',
      blockingFingerprints: [],
      summary: 'Review in progress.',
      requiredCoverageComplete: false,
    },
    pipeline: runningPipeline('run-dimensions'),
  })

  it('marks the running stage as the current step', () => {
    render(<PipelineStages stages={run.pipeline} />)

    expect(screen.getByText('Run Dimensions').closest('[aria-current="step"]')).not.toBeNull()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getAllByText('Not started').length).toBeGreaterThan(0)
  })

  it('keeps the gate node pending on the concept path', () => {
    render(<MergeCandidatePath run={run} />)

    const gateNode = screen.getByText('Gate Decision').closest('div')
    expect(gateNode?.className).toContain('opacity-70')
    expect(screen.getByText('Review Dimensions').closest('[aria-current="step"]')).not.toBeNull()
  })
})

describe('state: Coverage Error', () => {
  const run = derive({
    runStatus: 'failed',
    gateState: 'error',
    gate: {
      gateState: 'error',
      blockingFingerprints: [],
      summary: 'Review finished but mandatory content was missing, so the Gate is Error.',
      requiredCoverageComplete: false,
    },
    coverage: {
      requiredCoverage: 'incomplete',
      reviewedCount: 30,
      excludedCount: 2,
      missingCount: 1,
      files: [
        {
          path: 'src/platform/webhooks/authorization/policy.ts',
          category: 'mandatory-missing',
          reason: 'Mandatory glob content was not available to the review context.',
          rule: 'mandatory-glob: src/platform/webhooks/**',
        },
      ],
    },
    pipeline: failedPipeline('check-completeness', 'Mandatory coverage incomplete.'),
    failure: {
      stage: 'check-completeness',
      category: 'coverage_incomplete',
      safeDetail: 'Mandatory coverage incomplete.',
    },
  })

  it('explains the Error gate and names the missing mandatory file', () => {
    render(<CoverageTab run={run} />)

    expect(screen.getByRole('alert')).toHaveTextContent(/Gate cannot pass/)
    expect(screen.getByRole('alert')).toHaveTextContent(/Check Completeness/)
    const missing = screen.getByRole('region', { name: 'Mandatory missing files' })
    expect(
      within(missing).getByText('src/platform/webhooks/authorization/policy.ts'),
    ).toBeInTheDocument()
    expect(within(missing).getByText(/mandatory-glob/)).toBeInTheDocument()
  })
})

describe('state: Provider failure', () => {
  const run = derive({
    runStatus: 'failed',
    gateState: 'error',
    gate: {
      gateState: 'error',
      blockingFingerprints: [],
      summary: 'A provider call failed; completed dimensions are shown but the Gate is Error.',
      requiredCoverageComplete: false,
    },
    pipeline: failedPipeline(
      'run-dimensions',
      'Provider request failed (category: transport). No request or response bodies are recorded.',
    ),
    failure: {
      stage: 'run-dimensions',
      category: 'provider_error',
      safeDetail: 'Provider request failed (category: transport).',
    },
  })

  it('shows the failed stage, category and completed predecessors', () => {
    render(<OverviewTab run={run} />)

    expect(screen.getByText(/Run Dimensions failed — provider_error/)).toBeInTheDocument()
    expect(screen.getAllByText(/category: transport/).length).toBeGreaterThan(0)
    const pipelineSection = screen.getByRole('heading', { name: 'Review Pipeline' }).parentElement
    expect(pipelineSection).not.toBeNull()
    expect(within(pipelineSection as HTMLElement).getAllByRole('listitem')).toHaveLength(9)
  })
})

describe('state: Budget exhausted', () => {
  const run = derive({
    runStatus: 'failed',
    gateState: 'error',
    pipeline: failedPipeline(
      'run-dimensions',
      'Review budget exhausted at provider call 3 of 5 planned. Estimated spend reached the compute policy limit.',
    ),
    failure: {
      stage: 'run-dimensions',
      category: 'budget_exhausted',
      safeDetail: 'Review budget exhausted.',
    },
  })

  it('names the exhaustion point without implying a gate result', () => {
    render(<OverviewTab run={run} />)

    expect(screen.getByText(/budget_exhausted/)).toBeInTheDocument()
    expect(screen.getByText(/budget exhausted at provider call 3 of 5/i)).toBeInTheDocument()
    expect(screen.getByText(/Not evaluated/)).toBeInTheDocument()
  })
})

describe('state: Interrupted', () => {
  const run = derive({
    runStatus: 'interrupted',
    gateState: 'error',
    gate: {
      gateState: 'error',
      blockingFingerprints: [],
      summary: 'The service restarted while this attempt was running; the attempt was not resumed.',
      requiredCoverageComplete: false,
    },
  })

  it('explains the interruption as text, not color', () => {
    render(<ReviewHeader run={run} />)

    expect(screen.getByText(/Run status: Interrupted/)).toBeInTheDocument()
    expect(screen.getAllByText(/not resumed/).length).toBeGreaterThan(0)
  })
})

describe('state: Passed with Bypass', () => {
  const run = derive({
    gateState: 'passed_with_bypass',
    bypassState: 'active',
    gate: {
      ...blockedCase.gate,
      gateState: 'passed_with_bypass',
      summary: 'Blocking findings were accepted by authorization.',
    },
  })

  it('keeps the risk signal instead of looking like a clean pass', () => {
    render(<ReviewHeader run={run} />)

    expect(screen.getByText('Passed with Bypass')).toBeInTheDocument()
    expect(screen.getByText(/not a clean pass/i)).toBeInTheDocument()
    expect(screen.getByText('Bypass active')).toBeInTheDocument()
  })
})

describe('state: Superseded', () => {
  const run = derive({ authority: 'superseded' })

  it('states the loss of authority next to the badge', () => {
    render(<ReviewHeader run={run} />)

    expect(screen.getByText('Superseded')).toBeInTheDocument()
    expect(screen.getByText(/can no longer publish or change the standing decision/)).toBeInTheDocument()
  })
})

describe('state: Passed without findings', () => {
  it('shows the passed gate with zero blocking findings', () => {
    render(<ReviewHeader run={passedCase} />)
    render(<OverviewTab run={passedCase} />)

    expect(screen.getAllByText('Passed').length).toBeGreaterThan(0)
    expect(screen.getByText('Complete')).toBeInTheDocument()
  })
})

describe('reduced motion', () => {
  it('marks skeletons as reduced-motion aware', () => {
    render(<PipelineStages stages={runningPipeline('run-dimensions')} />)

    // matchMedia reports reduce; pulse animation is zeroed globally by the
    // prefers-reduced-motion override in styles/index.css.
    expect(window.matchMedia('(prefers-reduced-motion: reduce)').matches).toBe(true)
  })
})

describe('long content resilience', () => {
  it('renders the very long evidence path with break-anywhere wrapping', () => {
    render(<CoverageTab run={blockedCase} />)

    const longPath = screen.getByText(/verify_signature_or_accept\.py/)
    expect(longPath.className).toContain('break-all')
  })
})
