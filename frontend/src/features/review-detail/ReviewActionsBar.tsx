import type { LucideIcon } from 'lucide-react'
import { ExternalLink, Eye, RotateCcw, ShieldAlert } from 'lucide-react'
import { Button } from '../../components/ui/button.tsx'
import { Tooltip } from '../../components/ui/tooltip.tsx'
import type { AvailableReviewActionsView, ReviewActionCapabilityView } from '../../domain/review.ts'

interface ActionDefinition {
  key: keyof AvailableReviewActionsView
  label: string
  icon: LucideIcon
  capability: ReviewActionCapabilityView
}

/**
 * Renders Retry / Bypass / Open Check / Open Session Insight purely from the
 * capability view (visible / enabled / disabledReason). The prototype never
 * submits these actions; P0 delivers copy, capability state and reasons.
 */
export function ReviewActionsBar({ actions }: { actions: AvailableReviewActionsView }) {
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
  if (visible.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Review actions">
      {visible.map((definition) => {
        const { capability } = definition
        const button = (
          <Button variant="secondary" size="sm" disabled={!capability.enabled}>
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
  )
}
