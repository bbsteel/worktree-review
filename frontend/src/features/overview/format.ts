import type { BadgeTone } from '../../components/ui/badge.tsx'
import type { GateState, ReviewSourceView } from '../../domain/review.ts'

export function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return 'Not reported'
  }
  const totalSeconds = Math.round(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) {
    return `${String(seconds)}s`
  }
  return `${String(minutes)}m ${String(seconds).padStart(2, '0')}s`
}

export function formatCost(costUsd: number | null, costUnknown: boolean): string {
  if (costUnknown || costUsd === null) {
    return 'Unknown'
  }
  return `$${costUsd.toFixed(2)}`
}

export function formatPercent(value: number | null): string {
  if (value === null) {
    return 'n/a'
  }
  return `${(value * 100).toFixed(1)}%`
}

export function gateBadge(gateState: GateState): { tone: BadgeTone; label: string } {
  switch (gateState) {
    case 'passed':
      return { tone: 'passed', label: 'Passed' }
    case 'passed_with_bypass':
      return { tone: 'passed-with-bypass', label: 'Passed with Bypass' }
    case 'blocked':
      return { tone: 'blocked', label: 'Blocked' }
    case 'error':
      return { tone: 'error', label: 'Error' }
    case 'in_progress':
      return { tone: 'running', label: 'In Progress' }
    case 'awaiting_review':
      return { tone: 'awaiting', label: 'Awaiting Review' }
    default: {
      const exhaustive: never = gateState
      return exhaustive
    }
  }
}

export function sourceLabel(source: ReviewSourceView): string {
  if (source.kind === 'github-pull-request') {
    return `GitHub PR #${String(source.pullRequestNumber)}`
  }
  if (source.kind === 'local-worktree') {
    return 'Local worktree'
  }
  if (source.kind === 'local-recent-commits') {
    return 'Local recent commits'
  }
  return 'Local committed ref'
}

export function isGitHubSource(source: ReviewSourceView): boolean {
  return source.kind === 'github-pull-request'
}
