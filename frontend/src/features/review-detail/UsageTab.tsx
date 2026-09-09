import type { ReviewRunView } from '../../domain/review.ts'
import { formatCostUsd, formatDurationMs, formatTokenCount } from './formatting.ts'

/**
 * Usage tab (design 13.10). Estimated and actual cost are always separated;
 * unknown values render as Unknown with a reason, never as $0.00. Call
 * identity fields that the result schema did not record render as
 * "Not reported" — tuple position is never presented as call identity.
 */
export function UsageTab({ run }: { run: ReviewRunView }) {
  const usage = run.usage

  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Usage totals" className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">Totals</h2>
        <dl className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">Estimated cost</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {formatCostUsd(usage.estimatedCostUsd, usage.costUnknown)}
            </dd>
            <dd className="text-meta text-text-secondary">Pre-run estimate, not measured usage.</dd>
          </div>
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">Actual cost</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {formatCostUsd(usage.actualCostUsd, usage.costUnknown)}
            </dd>
            {usage.costUnknown ? (
              <dd className="text-meta text-status-warning">
                Unknown for {usage.unknownCostRecordCount} record
                {usage.unknownCostRecordCount === 1 ? '' : 's'} — the provider did not report a
                price for every call.
              </dd>
            ) : null}
          </div>
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">Input tokens</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {formatTokenCount(usage.inputTokens)}
            </dd>
          </div>
          <div className="rounded-md bg-surface-subtle p-3">
            <dt className="text-meta uppercase tracking-wide text-text-secondary">Output tokens</dt>
            <dd className="mt-1 text-lg font-semibold text-text-primary tabular-nums">
              {formatTokenCount(usage.outputTokens)}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label="Provider calls" className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">Provider calls</h2>
        {usage.calls.length === 0 ? (
          <p className="mt-2 text-sm text-text-secondary">
            No provider calls were recorded for this attempt.
            {usage.costUnknown
              ? ' Usage is unknown because no measured call records exist.'
              : ''}
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-left text-meta uppercase tracking-wide text-text-secondary">
                  <th scope="col" className="py-2 pr-3 font-medium">Call</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Dimension</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Provider / Model</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Elapsed</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Kind</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Input</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Output</th>
                  <th scope="col" className="py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {usage.calls.map((call, index) => (
                  <tr key={call.ordinal ?? index} className="border-b border-border last:border-b-0">
                    <td className="py-2 pr-3 font-mono text-text-primary tabular-nums">
                      {call.ordinal !== null ? `#${call.ordinal}` : 'Not reported'}
                    </td>
                    <td className="py-2 pr-3 font-mono text-text-primary">
                      {call.dimensionId ?? 'Not reported'}
                    </td>
                    <td className="py-2 pr-3 font-mono text-text-primary">
                      {call.provider} / {call.model}
                    </td>
                    <td className="py-2 pr-3 text-text-primary tabular-nums">
                      {call.elapsedMs !== null ? formatDurationMs(call.elapsedMs) : 'Not reported'}
                    </td>
                    <td className="py-2 pr-3 text-text-primary">{call.usageKind}</td>
                    <td className="py-2 pr-3 text-right text-text-primary tabular-nums">
                      {formatTokenCount(call.inputTokens)}
                    </td>
                    <td className="py-2 pr-3 text-right text-text-primary tabular-nums">
                      {formatTokenCount(call.outputTokens)}
                    </td>
                    <td className="py-2 text-right text-text-primary tabular-nums">
                      {formatCostUsd(call.costUsd, call.costUnknown)}
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
