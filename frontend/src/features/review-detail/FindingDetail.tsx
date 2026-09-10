import { useEffect, useRef } from 'react'
import { Badge } from '../../components/ui/badge.tsx'
import type { ReviewFindingView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { CopyValue } from './CopyValue.tsx'
import { EvidenceViewer } from './EvidenceViewer.tsx'
import { shortenFingerprint } from './formatting.ts'
import { EVIDENCE_BAND_PRESENTATION, SEVERITY_PRESENTATION } from './presentation.ts'

interface FindingDetailProps {
  finding: ReviewFindingView
}

/**
 * Finding detail pane (design 13.5). All model output renders as plain text.
 * No auto-fix, commit or push actions exist by design.
 */
export function FindingDetail({ finding }: FindingDetailProps) {
  const { t } = useI18n()
  const severity = SEVERITY_PRESENTATION[finding.severity]
  const band = EVIDENCE_BAND_PRESENTATION[finding.evidenceBand]
  const detailRef = useRef<HTMLDivElement>(null)

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
      </div>
    </div>
  )
}
