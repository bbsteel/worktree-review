import { usePrefersReducedMotion } from '../../app/motion.ts'
import { cx } from './cx.ts'

interface SkeletonProps {
  className?: string
  label?: string
}

export function Skeleton({ className, label = 'Loading' }: SkeletonProps) {
  const reduced = usePrefersReducedMotion()

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      data-reduced-motion={reduced ? 'true' : 'false'}
      className={cx(
        'rounded-md bg-surface-subtle',
        reduced ? undefined : 'animate-pulse',
        className,
      )}
    />
  )
}
