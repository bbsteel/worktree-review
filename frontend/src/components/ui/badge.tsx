import {
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleX,
  Clock,
  Info,
  OctagonX,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { cx } from './cx.ts'

export type BadgeTone =
  | 'neutral'
  | 'passed'
  | 'passed-with-bypass'
  | 'blocked'
  | 'error'
  | 'warning'
  | 'running'
  | 'awaiting'
  | 'critical'
  | 'major'
  | 'minor'
  | 'suggestion'

interface BadgeProps {
  tone?: BadgeTone
  label: string
  icon?: LucideIcon
  children?: ReactNode
  className?: string
}

const toneClass: Record<BadgeTone, string> = {
  neutral: 'text-text-secondary border-border',
  passed: 'text-status-passed border-status-passed',
  'passed-with-bypass': 'text-status-passed-with-bypass border-status-passed-with-bypass',
  blocked: 'text-status-blocked border-status-blocked',
  error: 'text-status-error border-status-error',
  warning: 'text-status-warning border-status-warning',
  running: 'text-status-running border-status-running',
  awaiting: 'text-status-awaiting border-status-awaiting',
  critical: 'text-severity-critical border-severity-critical',
  major: 'text-severity-major border-severity-major',
  minor: 'text-severity-minor border-severity-minor',
  suggestion: 'text-severity-suggestion border-severity-suggestion',
}

const defaultIcon: Record<BadgeTone, LucideIcon> = {
  neutral: Info,
  passed: CircleCheck,
  'passed-with-bypass': ShieldAlert,
  blocked: OctagonX,
  error: CircleX,
  warning: TriangleAlert,
  running: CircleDot,
  awaiting: Clock,
  critical: CircleAlert,
  major: OctagonX,
  minor: TriangleAlert,
  suggestion: Info,
}

const shapeClass: Record<BadgeTone, string> = {
  neutral: 'rounded-md',
  passed: 'rounded-md',
  'passed-with-bypass': 'rounded-md',
  blocked: 'rounded-md',
  error: 'rounded-md',
  warning: 'rounded-md',
  running: 'rounded-md',
  awaiting: 'rounded-md',
  critical: 'rounded-full',
  major: 'rounded-full',
  minor: 'rounded-full',
  suggestion: 'rounded-full',
}

export function Badge({ tone = 'neutral', label, icon, children, className }: BadgeProps) {
  const Icon = icon ?? defaultIcon[tone]

  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 border bg-surface px-2 py-1 text-xs font-medium',
        toneClass[tone],
        shapeClass[tone],
        className,
      )}
    >
      <Icon aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2} />
      <span>{label}</span>
      {children}
    </span>
  )
}
