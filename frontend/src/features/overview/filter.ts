import type { OverviewView } from '../../domain/overview.ts'
import type { ReviewSummaryView } from '../../domain/review.ts'
import { isGitHubSource } from './format.ts'

export type SurfaceFilter = 'all' | 'local' | 'github'

export function matchesSurface(summary: ReviewSummaryView, surface: SurfaceFilter): boolean {
  if (surface === 'all') {
    return true
  }
  const github = isGitHubSource(summary.source)
  return surface === 'github' ? github : !github
}

export function matchesRepository(summary: ReviewSummaryView, repository: string | null): boolean {
  if (!repository || repository === 'all') {
    return true
  }
  return summary.repositoryDisplayName === repository
}

export function filterSummaries(
  items: ReviewSummaryView[],
  repository: string | null,
  surface: SurfaceFilter,
): ReviewSummaryView[] {
  return items.filter(
    (item) => matchesRepository(item, repository) && matchesSurface(item, surface),
  )
}

export function filterOverviewLists(
  overview: OverviewView,
  repository: string | null,
  surface: SurfaceFilter,
): Pick<OverviewView, 'attention' | 'active' | 'recent'> {
  return {
    attention: filterSummaries(overview.attention, repository, surface),
    active: filterSummaries(overview.active, repository, surface),
    recent: filterSummaries(overview.recent, repository, surface),
  }
}
