import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import {
  blockedCase,
  errorMergeConflictCase,
  passedCase,
} from '../../data/fixtures/index.ts'
import { stubMatchMedia } from '../../test/match-media.ts'
import { MergeCandidatePath } from './MergeCandidatePath.tsx'
import { OverviewTab } from './OverviewTab.tsx'
import { PipelineStages } from './PipelineStages.tsx'

beforeAll(() => {
  stubMatchMedia({ '(prefers-reduced-motion: reduce)': false })
})

afterEach(() => {
  cleanup()
})

describe('OverviewTab', () => {
  it('shows gate, blocking, coverage and cost summaries first', () => {
    render(<OverviewTab run={blockedCase} />)

    expect(screen.getByText('Gate Decision')).toBeInTheDocument()
    expect(screen.getByText('Blocking Findings')).toBeInTheDocument()
    expect(screen.getByText('Required Coverage')).toBeInTheDocument()
    expect(screen.getByText('Cost (estimated / actual)')).toBeInTheDocument()

    const blockingTile = screen.getByText('Blocking Findings').parentElement
    expect(blockingTile).not.toBeNull()
    expect(within(blockingTile as HTMLElement).getByText(/1/)).toBeInTheDocument()
    expect(within(blockingTile as HTMLElement).getByText('finding')).toBeInTheDocument()
    expect(screen.getByText('Complete')).toBeInTheDocument()
    expect(screen.getByText('$0.40 / $0.42')).toBeInTheDocument()
  })

  it('renders dimensions dynamically from the run, with status text', () => {
    render(<OverviewTab run={blockedCase} />)

    const dimensions = screen.getByRole('heading', { name: 'Required Dimensions' }).parentElement
    expect(dimensions).not.toBeNull()
    for (const id of ['security', 'correctness', 'architecture', 'maintainability']) {
      expect(within(dimensions as HTMLElement).getByText(id)).toBeInTheDocument()
    }
    expect(within(dimensions as HTMLElement).getByText(/1 finding · 1 blocking/)).toBeInTheDocument()
  })

  it('shows provider health with observation time, not a fake live state', () => {
    render(<OverviewTab run={blockedCase} />)

    expect(screen.getByText(/Healthy at 2026-09-09 14:12:00 UTC/)).toBeInTheDocument()
    expect(screen.getByText(/OpenAI API \(United States\)/)).toBeInTheDocument()
  })

  it('marks blocking findings as not evaluated for an error gate', () => {
    render(<OverviewTab run={errorMergeConflictCase} />)

    expect(screen.getByText(/Not evaluated/)).toBeInTheDocument()
    expect(screen.getByText(/Construct Merge failed — merge_conflict/)).toBeInTheDocument()
    expect(
      screen.getAllByText(/git merge --no-commit --no-ff failed with conflicts/).length,
    ).toBeGreaterThan(0)
  })

  it('shows unknown cost as Unknown for the error case', () => {
    render(<OverviewTab run={errorMergeConflictCase} />)

    expect(screen.getByText('Unknown / Unknown')).toBeInTheDocument()
    expect(screen.getByText(/Actual cost unknown for 1 record/)).toBeInTheDocument()
  })

  it('shows a zero-blocking passed run without warnings', () => {
    render(<OverviewTab run={passedCase} />)

    const blockingTile = screen.getByText('Blocking Findings').parentElement
    expect(blockingTile).not.toBeNull()
    expect(within(blockingTile as HTMLElement).getByText(/0/)).toBeInTheDocument()
    expect(screen.queryByText(/Not evaluated/)).not.toBeInTheDocument()
  })
})

describe('PipelineStages', () => {
  it('completes all nine stages for a finished run', () => {
    render(<PipelineStages stages={blockedCase.pipeline} />)

    const stages = screen.getAllByRole('listitem')
    expect(stages).toHaveLength(9)
    expect(screen.getAllByText('Completed')).toHaveLength(9)
  })

  it('stops at the failed stage and exposes the safe detail via disclosure', async () => {
    const user = userEvent.setup()
    render(<PipelineStages stages={errorMergeConflictCase.pipeline} />)

    expect(screen.getByText('Derive Identity')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getAllByText('Not started').length).toBeGreaterThan(0)

    const summary = screen.getByText('Failure detail (safe summary)')
    await user.click(summary)
    expect(screen.getByText(/Conflict markers remain in the index/)).toBeInTheDocument()
  })
})

describe('MergeCandidatePath', () => {
  it('expresses that the exact merge result is reviewed', () => {
    render(<MergeCandidatePath run={blockedCase} />)

    expect(screen.getByText('Target + Proposed')).toBeInTheDocument()
    expect(screen.getByText('Exact Merge Tree')).toBeInTheDocument()
    expect(screen.getByText('Read-only Review Worktree')).toBeInTheDocument()
    expect(screen.getByText('Evidence Verification')).toBeInTheDocument()
    expect(screen.getByText('Gate Decision')).toBeInTheDocument()
  })

  it('terminates at the merge node when the merge candidate was not constructed', () => {
    render(<MergeCandidatePath run={errorMergeConflictCase} />)

    expect(screen.getByRole('alert')).toHaveTextContent(/Construct Merge failed/)
    const gateNode = screen.getByText('Gate Decision').closest('div')
    expect(gateNode?.className).toContain('opacity-70')
  })
})
