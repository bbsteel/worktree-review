import { useSearchParams } from 'react-router'
import { Badge } from '../../components/ui/badge.tsx'
import { Button } from '../../components/ui/button.tsx'
import { EmptyState } from '../../components/ui/empty-state.tsx'
import { cx } from '../../components/ui/cx.ts'
import type { ReviewFindingView, ReviewRunView } from '../../domain/review.ts'
import { FindingDetail } from './FindingDetail.tsx'
import { shortenFingerprint } from './formatting.ts'
import {
  filterFindings,
  isDefaultFindingFilter,
  readFindingFilter,
  writeFindingFilter,
  writeSelectedFinding,
  type FindingFilter,
} from './finding-filter.ts'
import { SEVERITY_PRESENTATION } from './presentation.ts'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'

interface FindingsTabProps {
  run: ReviewRunView
}

/**
 * Findings master/detail workspace (design 13.5). Selection and all filters
 * live in the URL query, so refresh and direct links keep the same view.
 * Filtering only changes the view; it never changes the Gate.
 */
export function FindingsTab({ run }: FindingsTabProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = readFindingFilter(searchParams)
  const filtered = filterFindings(run.findings, filter)

  const requestedFingerprint = searchParams.get('finding')
  const selected: ReviewFindingView | null =
    filtered.find((finding) => finding.fingerprint === requestedFingerprint) ?? filtered[0] ?? null

  function updateFilter(nextFilter: FindingFilter) {
    setSearchParams(writeFindingFilter(searchParams, nextFilter))
  }

  function selectFinding(fingerprint: string) {
    setSearchParams(writeSelectedFinding(searchParams, fingerprint))
  }

  if (run.findings.length === 0) {
    return (
      <EmptyState
        title="No findings"
        description="This attempt finished without findings. The gate result is shown in the Overview tab; this empty state is not a substituted success."
      />
    )
  }

  const dimensionIds = [...new Set(run.findings.map((finding) => finding.dimensionId))]

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="flex min-w-0 flex-col gap-3">
        <div
          role="group"
          aria-label="Finding filters"
          className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3"
        >
          <label className="flex flex-col gap-1 text-meta text-text-secondary">
            Search problem, path, or fingerprint
            <input
              type="search"
              value={filter.query}
              onChange={(event) => {
                updateFilter({ ...filter, query: event.target.value })
              }}
              className={FIELD_CLASS}
              placeholder="e.g. verify.py or fp_9f3c1a2b"
            />
          </label>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              Severity
              <select
                value={filter.severity}
                onChange={(event) => {
                  updateFilter({
                    ...filter,
                    severity: event.target.value as FindingFilter['severity'],
                  })
                }}
                className={FIELD_CLASS}
              >
                <option value="all">All severities</option>
                <option value="critical">Critical</option>
                <option value="major">Major</option>
                <option value="minor">Minor</option>
                <option value="suggestion">Suggestion</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              Dimension
              <select
                value={filter.dimensionId}
                onChange={(event) => {
                  updateFilter({ ...filter, dimensionId: event.target.value })
                }}
                className={FIELD_CLASS}
              >
                <option value="all">All dimensions</option>
                {dimensionIds.map((dimensionId) => (
                  <option key={dimensionId} value={dimensionId}>
                    {dimensionId}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              Evidence band
              <select
                value={filter.evidenceBand}
                onChange={(event) => {
                  updateFilter({
                    ...filter,
                    evidenceBand: event.target.value as FindingFilter['evidenceBand'],
                  })
                }}
                className={FIELD_CLASS}
              >
                <option value="all">All bands</option>
                <option value="supported">Supported</option>
                <option value="insufficient">Insufficient</option>
              </select>
            </label>
          </div>

          <label className="flex min-h-9 items-center gap-2 text-sm text-text-primary">
            <input
              type="checkbox"
              checked={filter.blockingOnly}
              onChange={(event) => {
                updateFilter({ ...filter, blockingOnly: event.target.checked })
              }}
              className="h-4 w-4 accent-[var(--wr-action-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            />
            Blocking only
          </label>

          <div className="flex items-center justify-between gap-2 text-meta text-text-secondary">
            <span aria-live="polite">
              {filtered.length} of {run.findings.length} findings
            </span>
            {!isDefaultFindingFilter(filter) ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  updateFilter({
                    query: '',
                    severity: 'all',
                    dimensionId: 'all',
                    evidenceBand: 'all',
                    blockingOnly: false,
                  })
                }}
              >
                Clear filters
              </Button>
            ) : null}
          </div>
        </div>

        {filtered.length === 0 ? (
          <EmptyState
            title="No findings match the filters"
            description="Filters only change this view. The gate result is unchanged."
          />
        ) : (
          <ul aria-label="Findings" className="flex flex-col gap-1">
            {filtered.map((finding) => {
              const severity = SEVERITY_PRESENTATION[finding.severity]
              const isSelected = selected?.fingerprint === finding.fingerprint
              return (
                <li key={finding.fingerprint}>
                  <button
                    type="button"
                    aria-current={isSelected ? 'true' : undefined}
                    onClick={() => {
                      selectFinding(finding.fingerprint)
                    }}
                    className={cx(
                      'flex w-full flex-col gap-1 rounded-md border px-3 py-2 text-left transition-colors duration-[var(--wr-motion-control)]',
                      'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring',
                      isSelected
                        ? 'border-action-primary bg-surface-subtle'
                        : 'border-border bg-surface hover:bg-surface-subtle',
                    )}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <Badge tone={severity.tone} label={severity.label} />
                      {finding.blocking ? <Badge tone="blocked" label="Blocking" /> : null}
                      <span className="font-mono text-meta text-text-secondary tabular-nums">
                        {shortenFingerprint(finding.fingerprint)}
                      </span>
                      <span className="font-mono text-meta text-text-secondary">
                        {finding.dimensionId}
                      </span>
                    </span>
                    <span className="text-sm text-text-primary">{finding.problemStatement}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="min-w-0">
        {selected !== null ? (
          <FindingDetail finding={selected} />
        ) : (
          <EmptyState
            title="Select a finding"
            description="Choose a finding on the left to inspect its evidence, impact and repair guidance."
          />
        )}
      </div>
    </div>
  )
}
