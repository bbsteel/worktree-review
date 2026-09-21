import { Badge, type BadgeTone } from '../../components/ui/badge.tsx'
import type { SessionInsightStatusView } from '../../domain/overview.ts'
import { useI18n } from '../../i18n.tsx'
import { formatTimestamp } from '../review-detail/formatting.ts'
import {
  configuredSessionInsightBaseUrl,
  SESSION_INSIGHT_STATE_PRESENTATION,
  sessionInsightDeepLink,
} from '../session-insight/session-insight.ts'

const STATE_TONE: Record<SessionInsightStatusView['state'], BadgeTone> = {
  connected: 'passed',
  disconnected: 'awaiting',
  incompatible: 'warning',
  disabled: 'neutral',
}

/**
 * Session Insight status card (design 5.5): the four connection states with
 * last probe time, current attempt and child session count. Observation is
 * advisory — it never affects the Review Gate.
 */
export function SessionInsightCard({ status }: { status: SessionInsightStatusView }) {
  const { t } = useI18n()
  const presentation = SESSION_INSIGHT_STATE_PRESENTATION[status.state]
  const deepLink =
    status.state === 'connected' && status.currentAttemptId !== null
      ? sessionInsightDeepLink(configuredSessionInsightBaseUrl(), status.currentAttemptId)
      : null

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={STATE_TONE[status.state]} label={t(presentation.label)} />
        {status.lastProbeAt !== null ? (
          <span className="text-meta text-text-secondary">
            {t('Last probed')} {formatTimestamp(status.lastProbeAt)}
          </span>
        ) : null}
      </div>
      <p className="mt-2 text-sm text-text-secondary">{t(presentation.description)}</p>
      {status.state === 'connected' ? (
        <dl className="mt-2 flex flex-col gap-1 text-meta text-text-secondary">
          <div className="flex gap-1.5">
            <dt>{t('Current attempt')}</dt>
            <dd className="font-mono text-text-primary">{status.currentAttemptId ?? t('none')}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>{t('Child sessions')}</dt>
            <dd className="text-text-primary tabular-nums">{status.childSessionCount}</dd>
          </div>
        </dl>
      ) : null}
      {status.state === 'connected' && status.currentAttemptId !== null && deepLink === null ? (
        <p className="mt-2 text-meta text-status-warning">
          {t('Session Insight address is not configured; the deep link is unavailable.')}
        </p>
      ) : null}
      {deepLink !== null ? (
        <a
          href={deepLink}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex min-h-9 items-center rounded-md border border-border px-2.5 text-sm text-action-primary hover:bg-surface-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          {t('Open current attempt in Session Insight')} ({new URL(deepLink).host})
        </a>
      ) : null}
    </div>
  )
}
