import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cx } from '../../components/ui/cx.ts'
import { shortenHash } from './formatting.ts'

interface CopyValueProps {
  /** Full machine identifier (hash, fingerprint, OID). Rendered as text only. */
  value: string
  /** Accessible name describing what is copied, e.g. "Review Identity". */
  label: string
  truncate?: boolean
  className?: string
}

/**
 * Copyable monospace identifier. Truncated by default; hover/focus reveals the
 * full value via the title attribute and the copy button always copies it.
 */
export function CopyValue({ value, label, truncate = true, className }: CopyValueProps) {
  const [copied, setCopied] = useState(false)
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (resetTimer.current !== null) {
        clearTimeout(resetTimer.current)
      }
    }
  }, [])

  async function copyValue() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      if (resetTimer.current !== null) {
        clearTimeout(resetTimer.current)
      }
      resetTimer.current = setTimeout(() => {
        setCopied(false)
      }, 1600)
    } catch {
      setCopied(false)
    }
  }

  const Icon = copied ? Check : Copy

  return (
    <span className={cx('inline-flex max-w-full items-center gap-1.5', className)}>
      <code
        title={value}
        className="min-w-0 truncate rounded-sm bg-code-background px-1.5 py-0.5 font-mono text-meta text-text-primary tabular-nums"
      >
        {truncate ? shortenHash(value) : value}
      </code>
      <button
        type="button"
        aria-label={`Copy ${label}`}
        onClick={() => {
          void copyValue()
        }}
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-colors duration-[var(--wr-motion-control)] hover:bg-surface-subtle hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      </button>
      <span aria-live="polite" className="sr-only">
        {copied ? `${label} copied` : ''}
      </span>
    </span>
  )
}
