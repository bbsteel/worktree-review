import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type ThemePreference } from '../../app/theme.ts'
import { cx } from './cx.ts'

const options: Array<{ value: ThemePreference; label: string; icon: typeof Moon }> = [
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'system', label: 'System', icon: Monitor },
]

export function ThemeSwitcher({ className }: { className?: string }) {
  const { preference, setPreference } = useTheme()

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className={cx('inline-flex rounded-md border border-border bg-surface p-1', className)}
    >
      {options.map((option) => {
        const selected = preference === option.value
        const Icon = option.icon
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            className={cx(
              'inline-flex min-h-10 items-center gap-1.5 rounded-sm px-2.5 text-sm',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring',
              selected ? 'bg-surface-subtle text-text-primary' : 'text-text-secondary hover:text-text-primary',
            )}
            onClick={() => {
              setPreference(option.value)
            }}
          >
            <Icon aria-hidden="true" className="h-4 w-4" />
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
