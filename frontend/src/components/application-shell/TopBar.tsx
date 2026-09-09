import { Plus } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useDataSource } from '../../app/data-source.ts'
import { ThemeSwitcher } from '../ui/theme-switcher.tsx'
import { Tooltip } from '../ui/tooltip.tsx'
import { formatProviderFreshness } from './format.ts'

export function TopBar() {
  const { overview } = useDataSource()
  const [searchParams, setSearchParams] = useSearchParams()
  const selected = searchParams.get('repository') ?? 'all'
  const repositories = useMemo(() => {
    const names = new Set<string>()
    for (const summary of overview?.recent ?? []) {
      names.add(summary.repositoryDisplayName)
    }
    return [...names].sort()
  }, [overview])
  const providerLabel = formatProviderFreshness(overview?.providerHealth[0])

  return (
    <div className="flex min-h-14 flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-2">
      <label className="flex min-h-10 items-center gap-2 text-sm text-text-secondary">
        <span className="sr-only">Repository</span>
        <select
          aria-label="Repository"
          className="min-h-10 rounded-md border border-border bg-background px-2 text-sm text-text-primary"
          value={selected}
          onChange={(event) => {
            const next = new URLSearchParams(searchParams)
            if (event.target.value === 'all') {
              next.delete('repository')
            } else {
              next.set('repository', event.target.value)
            }
            setSearchParams(next)
          }}
        >
          <option value="all">All repositories</option>
          {repositories.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <p className="hidden text-xs text-text-secondary lg:block" data-testid="provider-freshness">
        {providerLabel}
      </p>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <ThemeSwitcher />
        <Tooltip content="Local prototype environment. No authenticated user in this mode.">
          <button
            type="button"
            className="inline-flex min-h-10 items-center rounded-md border border-border px-2.5 text-sm text-text-secondary"
          >
            Local
          </button>
        </Tooltip>
        <Link
          to="/reviews/new"
          className="inline-flex min-h-10 items-center gap-2 rounded-md bg-action-primary px-3 text-sm font-medium text-background transition-[filter] duration-[var(--wr-motion-control)] hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <Plus aria-hidden="true" className="h-4 w-4" />
          New Review
        </Link>
        <span className="sr-only">
          Global search is hidden until Review and Attempt search is implemented.
        </span>
      </div>
    </div>
  )
}
