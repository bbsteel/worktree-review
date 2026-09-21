import { Inbox, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cx } from './cx.ts'

interface EmptyStateProps {
  title: string
  description: string
  icon?: LucideIcon
  action?: ReactNode
  className?: string
}

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cx(
        'flex flex-col items-start gap-2 rounded-lg border border-border bg-surface p-4',
        className,
      )}
    >
      <Icon aria-hidden="true" className="h-5 w-5 text-text-secondary" />
      <h2 className="text-base font-semibold text-text-primary">{title}</h2>
      <p className="text-sm text-text-secondary">{description}</p>
      {action}
    </div>
  )
}
