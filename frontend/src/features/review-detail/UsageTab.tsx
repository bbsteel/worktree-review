import type { ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { formatCostUsd, formatDurationMs, formatTokenCount } from './formatting.ts'

/**
 * Narrow viewports convert each row to a labeled list via data-th pseudo
 * labels instead of squeezing columns (design 21.2).
 */
const CELL_CLASS =
  'py-2 pr-3 text-text-primary max-sm:flex max-sm:items-baseline max-sm:justify-between max-sm:gap-3 max-sm:py-0.5 max-sm:pr-0 max-sm:text-left max-sm:before:content-[attr(data-th)] max-sm:before:text-meta max-sm:before:uppercase max-sm:before:tracking-wide max-sm:before:text-text-secondary'

/**
 * Usage tab (design 13.10). Estimated and actual cost are always separated;
 * unknown values render as Unknown with a reason, never as $0.00. Call
 * identity fields that the result schema did not record render as
 * "Not reported" — tuple position is never presented as call identity.
 */
export function UsageTab({ run }: { run: ReviewRunView }) {
  const { t } = useI18n()
  const usage = run.usage

  return (
    <div className="flex flex-col gap-4">
      <section aria-label={t('Usage totals')} className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">{t('Totals')}</h2>
        <dl className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">{t('Estimated cost')}</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {t(formatCostUsd(usage.estimatedCostUsd, usage.costUnknown))}
            </dd>
            <dd className="text-meta text-text-secondary">{t('Pre-run estimate, not measured usage.')}</dd>
          </div>
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">{t('Actual cost')}</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {t(formatCostUsd(usage.actualCostUsd, usage.costUnknown))}
            </dd>
            {usage.costUnknown ? (
              <dd className="text-meta text-status-warning">
                {t('Unknown for {count} record{suffix} — the provider did not report a price for every call.', {
                  count: usage.unknownCostRecordCount,
                  suffix: usage.unknownCostRecordCount === 1 ? '' : 's',
                })}
              </dd>
            ) : null}
          </div>
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">{t('Input tokens')}</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {t(formatTokenCount(usage.inputTokens))}
            </dd>
          </div>
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">{t('Output tokens')}</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {t(formatTokenCount(usage.outputTokens))}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label={t('Provider calls')} className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">{t('Provider calls')}</h2>
        {usage.calls.length === 0 ? (
          <p className="mt-2 text-sm text-text-secondary">
            {t('No provider calls were recorded for this attempt.')}
            {usage.costUnknown
              ? ` ${t('Usage is unknown because no measured call records exist.')}`
              : ''}
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm max-sm:block max-sm:min-w-0">
              <thead className="max-sm:sr-only">
                <tr className="border-b border-border text-left text-meta uppercase tracking-wide text-text-secondary">
                  <th scope="col" className="py-2 pr-3 font-medium">{t('Call')}</th>
                  <th scope="col" className="py-2 pr-3 font-medium">{t('Dimension')}</th>
                  <th scope="col" className="py-2 pr-3 font-medium">{t('Provider / Model')}</th>
                  <th scope="col" className="py-2 pr-3 font-medium">{t('Elapsed')}</th>
                  <th scope="col" className="py-2 pr-3 font-medium">{t('Kind')}</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">{t('Input')}</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">{t('Output')}</th>
                  <th scope="col" className="py-2 text-right font-medium">{t('Cost')}</th>
                </tr>
              </thead>
              <tbody className="max-sm:block">
                {usage.calls.map((call, index) => (
                  <tr
                    key={call.ordinal ?? index}
                    className="border-b border-border last:border-b-0 max-sm:flex max-sm:flex-col max-sm:gap-1 max-sm:py-3"
                  >
                    <td data-th={t('Call')} className={`${CELL_CLASS} font-mono tabular-nums`}>
                      {call.ordinal !== null ? `#${call.ordinal}` : t('Not reported')}
                    </td>
                    <td data-th={t('Dimension')} className={`${CELL_CLASS} font-mono`}>
                      {call.dimensionId ?? t('Not reported')}
                    </td>
                    <td data-th={t('Provider / Model')} className={`${CELL_CLASS} font-mono`}>
                      {call.provider} / {call.model}
                    </td>
                    <td data-th={t('Elapsed')} className={`${CELL_CLASS} tabular-nums`}>
                      {call.elapsedMs !== null ? t(formatDurationMs(call.elapsedMs)) : t('Not reported')}
                    </td>
                    <td data-th={t('Kind')} className={CELL_CLASS}>
                      {call.usageKind}
                    </td>
                    <td data-th={t('Input')} className={`${CELL_CLASS} text-right tabular-nums`}>
                      {t(formatTokenCount(call.inputTokens))}
                    </td>
                    <td data-th={t('Output')} className={`${CELL_CLASS} text-right tabular-nums`}>
                      {t(formatTokenCount(call.outputTokens))}
                    </td>
                    <td data-th={t('Cost')} className={`${CELL_CLASS} text-right tabular-nums`}>
                      {t(formatCostUsd(call.costUsd, call.costUnknown))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
