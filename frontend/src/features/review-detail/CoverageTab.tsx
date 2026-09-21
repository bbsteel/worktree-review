import { Badge } from '../../components/ui/badge.tsx'
import type { CoverageCategory, CoverageFileView, ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { COVERAGE_CATEGORY_PRESENTATION, PIPELINE_STAGE_LABEL } from './presentation.ts'

const CATEGORY_ORDER: CoverageCategory[] = [
  'reviewed',
  'mandatory-missing',
  'optional-missing',
  'excluded',
  'unreviewable',
]

const CATEGORY_BADGE_TONE: Record<CoverageCategory, 'passed' | 'error' | 'warning' | 'neutral'> = {
  reviewed: 'passed',
  'mandatory-missing': 'error',
  'optional-missing': 'warning',
  excluded: 'neutral',
  unreviewable: 'error',
}

/**
 * Coverage tab (design 13.6). Files are grouped by category with explicit
 * reasons; a single percentage never hides missing content. When the schema
 * did not record a reason, the UI says so instead of guessing.
 */
export function CoverageTab({ run }: { run: ReviewRunView }) {
  const { t } = useI18n()
  const coverage = run.coverage
  const groups = new Map<CoverageCategory, CoverageFileView[]>()
  for (const file of coverage.files) {
    const bucket = groups.get(file.category) ?? []
    bucket.push(file)
    groups.set(file.category, bucket)
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-text-primary">{t('Required Coverage')}</h2>
          {coverage.requiredCoverage === 'complete' ? (
            <Badge tone="passed" label={t('Complete')} />
          ) : (
            <Badge tone="error" label={t('Incomplete')} />
          )}
        </div>
        <p className="mt-2 text-sm text-text-secondary">
          {coverage.reviewedCount} {t('reviewed')} · {coverage.missingCount} {t('missing')} ·{' '}
          {coverage.excludedCount} {t('excluded')}
        </p>
        {coverage.requiredCoverage === 'incomplete' ? (
          <p role="alert" className="mt-2 text-sm text-status-error">
            {t('Required content was not fully reviewed, so the Gate cannot pass.')}
            {run.failure !== null
              ? ` ${t('The failure was recorded at stage {stage}.', {
                  stage: t(PIPELINE_STAGE_LABEL[run.failure.stage]),
                })}`
              : ''}
          </p>
        ) : null}
      </section>

      {CATEGORY_ORDER.map((category) => {
        const files = groups.get(category)
        if (files === undefined || files.length === 0) {
          return null
        }
        const presentation = COVERAGE_CATEGORY_PRESENTATION[category]
        return (
          <section
            key={category}
            aria-label={t('{label} files', { label: t(presentation.label) })}
            className="rounded-lg border border-border bg-surface p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={CATEGORY_BADGE_TONE[category]} label={t(presentation.label)} />
              <span className="text-meta text-text-secondary">
                {files.length} {t(files.length === 1 ? 'file' : 'files')} — {t(presentation.description)}
              </span>
            </div>
            <ul className="mt-3 flex flex-col gap-2">
              {files.map((file) => (
                <li
                  key={`${file.category}:${file.path}`}
                  className="rounded-md border border-border bg-surface-subtle px-3 py-2"
                >
                  <p className="break-all font-mono text-sm text-text-primary">{file.path}</p>
                  {category !== 'reviewed' ? (
                                    <p className="mt-1 text-meta text-text-secondary">
                                      {file.reason ?? t('Reason not reported by this result schema.')}
                                    </p>
                  ) : null}
                  {file.rule !== null ? (
                    <p className="mt-0.5 font-mono text-meta text-text-secondary">
                      {t('rule: {rule}', { rule: file.rule })}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
