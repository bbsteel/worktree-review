import { useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { ExternalLink, Eye, RotateCcw, ShieldAlert } from 'lucide-react'
import { Button } from '../../components/ui/button.tsx'
import { Tooltip } from '../../components/ui/tooltip.tsx'
import type { AvailableReviewActionsView, ReviewActionCapabilityView, ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import {
  configuredSessionInsightBaseUrl,
  sessionInsightDeepLink,
} from '../session-insight/session-insight.ts'
import { BypassRiskDialog } from './BypassRiskDialog.tsx'
import { RetryConfirmDialog } from './RetryConfirmDialog.tsx'

interface ActionDefinition {
  key: keyof AvailableReviewActionsView
  label: string
  icon: LucideIcon
  capability: ReviewActionCapabilityView
}

type ActiveDialog = 'retry' | 'bypass' | null

/**
 * Renders Retry / Bypass / Open Check / Open Session Insight purely from the
 * capability view (visible / enabled / disabledReason). Disabled actions show
 * their reason in a focusable tooltip. Enabled Retry/Bypass open the target
 * confirmation dialogs (B-014); this prototype never submits these actions —
 * confirming only simulates the interaction locally and sends no request.
 */
export function ReviewActionsBar({ run }: { run: ReviewRunView }) {
  const { t } = useI18n()
  const { availableActions: actions } = run
  const [activeDialog, setActiveDialog] = useState<ActiveDialog>(null)
  const [simulatedAction, setSimulatedAction] = useState<string | null>(null)

  const sessionInsightLink = sessionInsightDeepLink(
    configuredSessionInsightBaseUrl(),
    run.attemptId,
  )
  const checkUrl = run.source.kind === 'github-pull-request' ? run.source.checkUrl : null

  const definitions: ActionDefinition[] = [
    { key: 'retry', label: t('Retry'), icon: RotateCcw, capability: actions.retry },
    { key: 'bypass', label: t('Bypass'), icon: ShieldAlert, capability: actions.bypass },
    { key: 'openCheck', label: t('Open Check'), icon: ExternalLink, capability: actions.openCheck },
    {
      key: 'openSessionInsight',
      label: t('Open Session Insight'),
      icon: Eye,
      capability: actions.openSessionInsight,
    },
  ]

  const visible = definitions.filter((definition) => definition.capability.visible)

  function onSimulatedConfirm(label: string) {
    setSimulatedAction(t(label))
  }

  return (
    <div className="flex flex-col gap-2">
      {visible.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2" aria-label={t('Review actions')}>
          {visible.map((definition) => {
            const { capability } = definition

            // Open Check / Open Session Insight are navigation actions: when
            // the capability is enabled and the target URL exists, they are
            // real external links showing the destination host (design 19.4).
            if (
              (definition.key === 'openCheck' || definition.key === 'openSessionInsight') &&
              capability.enabled
            ) {
              const href = definition.key === 'openCheck' ? checkUrl : sessionInsightLink
              if (href !== null) {
                return (
                  <a
                    key={definition.key}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-9 items-center gap-2 rounded-md border border-border bg-surface px-2.5 text-sm font-medium text-text-primary transition-colors duration-[var(--wr-motion-control)] hover:bg-surface-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                  >
                    <definition.icon aria-hidden="true" className="h-4 w-4" />
                    {definition.label} ({new URL(href).host})
                  </a>
                )
              }
              const missingReason =
                definition.key === 'openCheck'
                  ? t('No GitHub Check URL was recorded for this attempt.')
                  : t('Session Insight address is not configured in this environment.')
              return (
                <Tooltip key={definition.key} content={missingReason}>
                  <span
                    tabIndex={0}
                    aria-label={t('{label} unavailable: {reason}', {
                      label: definition.label,
                      reason: missingReason,
                    })}
                    className="inline-flex rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                  >
                    <Button variant="secondary" size="sm" disabled>
                      <definition.icon aria-hidden="true" className="h-4 w-4" />
                      {definition.label}
                    </Button>
                  </span>
                </Tooltip>
              )
            }

            const opensDialog = definition.key === 'retry' || definition.key === 'bypass'
            const button = (
              <Button
                variant="secondary"
                size="sm"
                disabled={!capability.enabled}
                onClick={
                  capability.enabled && opensDialog
                    ? () => setActiveDialog(definition.key as ActiveDialog)
                    : undefined
                }
              >
                <definition.icon aria-hidden="true" className="h-4 w-4" />
                {definition.label}
              </Button>
            )

            if (capability.enabled || capability.disabledReason === null) {
              return <span key={definition.key}>{button}</span>
            }

            return (
              <Tooltip key={definition.key} content={capability.disabledReason}>
                <span
                  tabIndex={0}
                  aria-label={t('{label} unavailable: {reason}', {
                    label: definition.label,
                    reason: capability.disabledReason,
                  })}
                  className="inline-flex rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                >
                  {button}
                </span>
              </Tooltip>
            )
          })}
        </div>
      ) : null}

      {simulatedAction !== null ? (
        <p role="status" className="text-meta text-text-secondary">
          {t('{action} confirmed — simulated locally. This Pre-Alpha prototype sent no request and no state was changed.', {
            action: simulatedAction,
          })}
        </p>
      ) : null}

      <RetryConfirmDialog
        open={activeDialog === 'retry'}
        run={run}
        onClose={() => setActiveDialog(null)}
        onConfirm={() => onSimulatedConfirm('Retry')}
      />
      <BypassRiskDialog
        open={activeDialog === 'bypass'}
        run={run}
        onClose={() => setActiveDialog(null)}
        onConfirm={() => onSimulatedConfirm('Bypass')}
      />
    </div>
  )
}
