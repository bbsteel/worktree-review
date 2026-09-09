import { useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { ExternalLink, Eye, RotateCcw, ShieldAlert } from 'lucide-react'
import { Button } from '../../components/ui/button.tsx'
import { Tooltip } from '../../components/ui/tooltip.tsx'
import type { AvailableReviewActionsView, ReviewActionCapabilityView, ReviewRunView } from '../../domain/review.ts'
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
  const { availableActions: actions } = run
  const [activeDialog, setActiveDialog] = useState<ActiveDialog>(null)
  const [simulatedAction, setSimulatedAction] = useState<string | null>(null)

  const definitions: ActionDefinition[] = [
    { key: 'retry', label: 'Retry', icon: RotateCcw, capability: actions.retry },
    { key: 'bypass', label: 'Bypass', icon: ShieldAlert, capability: actions.bypass },
    { key: 'openCheck', label: 'Open Check', icon: ExternalLink, capability: actions.openCheck },
    {
      key: 'openSessionInsight',
      label: 'Open Session Insight',
      icon: Eye,
      capability: actions.openSessionInsight,
    },
  ]

  const visible = definitions.filter((definition) => definition.capability.visible)

  function onSimulatedConfirm(label: string) {
    setSimulatedAction(label)
  }

  return (
    <div className="flex flex-col gap-2">
      {visible.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2" aria-label="Review actions">
          {visible.map((definition) => {
            const { capability } = definition
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
                  aria-label={`${definition.label} unavailable: ${capability.disabledReason}`}
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
          {simulatedAction} confirmed — simulated locally. This Pre-Alpha prototype sent no request
          and no state was changed.
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
