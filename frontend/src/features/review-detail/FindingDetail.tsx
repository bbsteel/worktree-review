import { useEffect, useRef } from 'react'
import { Badge } from '../../components/ui/badge.tsx'
import { Button } from '../../components/ui/button.tsx'
import { Tooltip } from '../../components/ui/tooltip.tsx'
import type { ReviewFindingView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { CopyValue } from './CopyValue.tsx'
import { EvidenceViewer } from './EvidenceViewer.tsx'
import { formatTimestamp, shortenFingerprint } from './formatting.ts'
import { EVIDENCE_BAND_PRESENTATION, SEVERITY_PRESENTATION } from './presentation.ts'

interface FindingDetailProps {
  finding: ReviewFindingView
  /**
   * Present only when the run's bypass capability is available (authorized
   * GitHub deployment). The server still re-authorizes every submission.
   */
  bypassAction?: {
    enabled: boolean
    disabledReason: string | null
    onAcceptRisk: () => void
  }
}

/**
 * Finding detail pane (design 13.5). All model output renders as plain text.
 * No auto-fix, commit or push actions exist by design. An active risk
 * acceptance is shown with actor, time and reason; invalidated acceptances
 * remain visible as history (P3 §9.1).
 */
export function FindingDetail({ finding, bypassAction }: FindingDetailProps) {
  const { t } = useI18n()
  const severity = SEVERITY_PRESENTATION[finding.severity]
  const band = EVIDENCE_BAND_PRESENTATION[finding.evidenceBand]
  const detailRef = useRef<HTMLDivElement>(null)
  const bypassRecord = finding.bypassRecord ?? null

  useEffect(() => {
    const element = detailRef.current
    if (element && typeof element.scrollIntoView === 'function') {
      element.scrollIntoView({ block: 'nearest' })
    }
  }, [finding.fingerprint])

  return (
    <div ref={detailRef} className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={severity.tone} label={t(severity.label)} />
        <Badge tone="neutral" label={t(band.label)} />
        <span className="font-mono text-meta text-text-secondary">{finding.dimensionId}</span>
        {finding.blocking ? <Badge tone="blocked" label={t('Blocking')} /> : null}
      </div>

      <h3 className="mt-3 text-base font-semibold text-text-primary">{finding.problemStatement}</h3>

      <div className="mt-3 flex flex-col gap-3">
        <section>
          <h4 className="text-meta font-semibold uppercase tracking-wide text-text-secondary">
            {t('Expected impact')}
          </h4>
          <p className="mt-1 text-sm text-text-primary">{finding.expectedImpact}</p>
        </section>

        <section>
          <h4 className="text-meta font-semibold uppercase tracking-wide text-text-secondary">
            {t('Repair guidance')}
          </h4>
          <p className="mt-1 text-sm text-text-primary">{finding.repairGuidance}</p>
          <p className="mt-1 text-meta text-text-secondary">
            {t('Guidance only — Worktree Review never modifies, commits or pushes the reviewed code.')}
          </p>
        </section>

        <section>
          <h4 className="text-meta font-semibold uppercase tracking-wide text-text-secondary">
            {t('Evidence ({count})', { count: finding.evidenceSpans.length })}
          </h4>
          <div className="mt-2 flex flex-col gap-3">
            {finding.evidenceSpans.map((span) => (
              <EvidenceViewer
                key={`${span.path}:${span.startLine}-${span.endLine}`}
                span={span}
              />
            ))}
          </div>
        </section>

        <section>
          <h4 className="text-meta font-semibold uppercase tracking-wide text-text-secondary">
            {t('Fingerprint')}
          </h4>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-text-primary tabular-nums">
              {shortenFingerprint(finding.fingerprint)}
            </span>
            <CopyValue value={finding.fingerprint} label={t('finding fingerprint')} truncate={false} />
          </div>
          <p className="mt-1 text-meta text-text-secondary">
            {t('Evidence band: {label} — {description}', {
              label: t(band.label),
              description: t(band.description),
            })}
          </p>
        </section>

        {bypassRecord !== null && bypassRecord.status === 'active' ? (
          <section
            aria-label={t('Accepted risk')}
            className="rounded-md border border-status-warning/40 bg-surface-subtle p-3"
          >
            <h4 className="text-meta font-semibold uppercase tracking-wide text-text-secondary">
              {t('Accepted risk')}
            </h4>
            <p className="mt-1 text-sm text-text-primary">{bypassRecord.reason}</p>
            <p className="mt-1 text-meta text-text-secondary">
              {t('Accepted by {actor} · {time}', {
                actor: bypassRecord.actorLogin,
                time: formatTimestamp(bypassRecord.createdAt),
              })}
            </p>
          </section>
        ) : null}

        {bypassRecord !== null && bypassRecord.status === 'invalidated' ? (
          <section
            aria-label={t('Bypass history')}
            className="rounded-md border border-border bg-surface-subtle p-3"
          >
            <h4 className="text-meta font-semibold uppercase tracking-wide text-text-secondary">
              {t('Bypass history (no longer applies)')}
            </h4>
            <p className="mt-1 text-sm text-text-primary">{bypassRecord.reason}</p>
            <p className="mt-1 text-meta text-text-secondary">
              {t('Accepted by {actor} · invalidated: {reason}', {
                actor: bypassRecord.actorLogin,
                reason: bypassRecord.invalidationReason ?? t('unknown'),
              })}
            </p>
          </section>
        ) : null}

        {bypassAction !== undefined && finding.blocking && bypassRecord?.status !== 'active' ? (
          <section aria-label={t('Risk acceptance')}>
            {bypassAction.enabled ? (
              <Button variant="danger" size="sm" onClick={bypassAction.onAcceptRisk}>
                {t('Accept risk…')}
              </Button>
            ) : (
              <Tooltip content={bypassAction.disabledReason ?? ''}>
                <span
                  tabIndex={0}
                  aria-label={t('Accept risk unavailable: {reason}', {
                    reason: bypassAction.disabledReason ?? '',
                  })}
                  className="inline-flex rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                >
                  <Button variant="danger" size="sm" disabled>
                    {t('Accept risk…')}
                  </Button>
                </span>
              </Tooltip>
            )}
            <p className="mt-1 text-meta text-text-secondary">
              {t('Bypass means accepting the risk. It does not mean the finding was resolved.')}
            </p>
          </section>
        ) : null}
      </div>
    </div>
  )
}
