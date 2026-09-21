import type { LucideIcon } from 'lucide-react'
import { useId } from 'react'
import { useI18n } from '../../i18n.tsx'
import { cx } from './cx.ts'
import { Tooltip } from './tooltip.tsx'

interface PreviewControlProps {
  label: string
  reason: string
  icon?: LucideIcon
  className?: string
}

export function PreviewControl({ label, reason, icon: Icon, className }: PreviewControlProps) {
  const descriptionId = useId()
  const { t } = useI18n()

  return (
    <Tooltip content={reason}>
      <span
        className={cx('inline-flex', className)}
        tabIndex={0}
        role="button"
        aria-disabled="true"
        aria-describedby={descriptionId}
      >
        <span
          className={cx(
            'inline-flex min-h-10 cursor-not-allowed items-center gap-2 rounded-md px-2.5 text-sm text-text-secondary opacity-70',
          )}
        >
          {Icon ? <Icon aria-hidden="true" className="h-4 w-4" /> : null}
          <span>{label}</span>
          <span className="rounded-sm border border-border px-1 text-[11px] uppercase tracking-wide">
            {t('Preview')}
          </span>
        </span>
        <span id={descriptionId} className="sr-only">
          {reason}
        </span>
      </span>
    </Tooltip>
  )
}
