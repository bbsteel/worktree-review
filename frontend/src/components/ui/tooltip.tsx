import { cloneElement, isValidElement, useId, useState, type FocusEvent, type MouseEvent, type ReactElement } from 'react'
import { cx } from './cx.ts'

interface TooltipProps {
  content: string
  children: ReactElement
  className?: string
}

export function Tooltip({ content, children, className }: TooltipProps) {
  const tooltipId = useId()
  const [open, setOpen] = useState(false)

  if (!isValidElement(children)) {
    throw new Error('Tooltip requires a single React element child')
  }

  const child = children as ReactElement<{
    'aria-describedby'?: string
    onBlur?: (event: FocusEvent) => void
    onFocus?: (event: FocusEvent) => void
    onMouseEnter?: (event: MouseEvent) => void
    onMouseLeave?: (event: MouseEvent) => void
  }>

  return (
    <span className={cx('relative inline-flex', className)}>
      {cloneElement(child, {
        'aria-describedby': [child.props['aria-describedby'], open ? tooltipId : null]
          .filter(Boolean)
          .join(' ') || undefined,
        onFocus: (event: FocusEvent) => {
          child.props.onFocus?.(event)
          setOpen(true)
        },
        onBlur: (event: FocusEvent) => {
          child.props.onBlur?.(event)
          setOpen(false)
        },
        onMouseEnter: (event: MouseEvent) => {
          child.props.onMouseEnter?.(event)
          setOpen(true)
        },
        onMouseLeave: (event: MouseEvent) => {
          child.props.onMouseLeave?.(event)
          setOpen(false)
        },
      })}
      {open ? (
        <span
          role="tooltip"
          id={tooltipId}
          className="absolute bottom-full left-1/2 z-40 mb-2 -translate-x-1/2 whitespace-nowrap rounded-sm border border-border bg-surface px-2 py-1 text-xs text-text-primary shadow-[var(--wr-shadow-overlay)]"
        >
          {content}
        </span>
      ) : null}
    </span>
  )
}
