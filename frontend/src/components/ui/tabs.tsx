import {
  createContext,
  useContext,
  useId,
  useMemo,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { cx } from './cx.ts'

interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
  baseId: string
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabsContext(): TabsContextValue {
  const value = useContext(TabsContext)
  if (!value) {
    throw new Error('Tabs components must be used within Tabs')
  }
  return value
}

interface TabsProps {
  value: string
  onValueChange: (value: string) => void
  children: ReactNode
  className?: string
}

export function Tabs({ value, onValueChange, children, className }: TabsProps) {
  const baseId = useId()
  const context = useMemo(
    () => ({ value, onValueChange, baseId }),
    [value, onValueChange, baseId],
  )

  return (
    <TabsContext.Provider value={context}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

interface TabListProps {
  children: ReactNode
  'aria-label': string
  className?: string
}

export function TabList({ children, className, ...props }: TabListProps) {
  const listRef = useRef<HTMLDivElement>(null)

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const tabs = [...(listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [])]
    if (tabs.length === 0) {
      return
    }

    const currentIndex = tabs.findIndex((tab) => tab === document.activeElement)
    if (currentIndex < 0) {
      return
    }

    let nextIndex = currentIndex
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (currentIndex + 1) % tabs.length
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
    } else if (event.key === 'Home') {
      nextIndex = 0
    } else if (event.key === 'End') {
      nextIndex = tabs.length - 1
    } else {
      return
    }

    event.preventDefault()
    tabs[nextIndex]?.focus()
    tabs[nextIndex]?.click()
  }

  return (
    <div
      ref={listRef}
      role="tablist"
      className={cx('flex gap-1 border-b border-border', className)}
      onKeyDown={onKeyDown}
      {...props}
    >
      {children}
    </div>
  )
}

interface TabProps {
  value: string
  children: ReactNode
}

export function Tab({ value, children }: TabProps) {
  const tabs = useTabsContext()
  const selected = tabs.value === value

  return (
    <button
      type="button"
      role="tab"
      id={`${tabs.baseId}-tab-${value}`}
      aria-selected={selected}
      aria-controls={`${tabs.baseId}-panel-${value}`}
      tabIndex={selected ? 0 : -1}
      className={cx(
        '-mb-px border-b-2 px-3 py-2 text-sm transition-colors duration-[var(--wr-motion-control)]',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring',
        selected
          ? 'border-action-primary text-text-primary'
          : 'border-transparent text-text-secondary hover:text-text-primary',
      )}
      onClick={() => {
        tabs.onValueChange(value)
      }}
    >
      {children}
    </button>
  )
}

interface TabPanelProps {
  value: string
  children: ReactNode
  className?: string
}

export function TabPanel({ value, children, className }: TabPanelProps) {
  const tabs = useTabsContext()
  const selected = tabs.value === value

  if (!selected) {
    return null
  }

  return (
    <div
      role="tabpanel"
      id={`${tabs.baseId}-panel-${value}`}
      aria-labelledby={`${tabs.baseId}-tab-${value}`}
      className={cx('pt-3', className)}
    >
      {children}
    </div>
  )
}
