import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx.ts'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'md' | 'sm' | 'icon'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  children: ReactNode
}

const variantClass: Record<ButtonVariant, string> = {
  primary:
    'bg-action-primary text-background hover:brightness-110 disabled:bg-surface-subtle disabled:text-text-secondary',
  secondary:
    'bg-surface text-text-primary border border-border hover:bg-surface-subtle disabled:text-text-secondary',
  ghost: 'bg-transparent text-text-primary hover:bg-surface-subtle disabled:text-text-secondary',
  danger: 'bg-status-error text-background hover:brightness-110 disabled:bg-surface-subtle disabled:text-text-secondary',
}

const sizeClass: Record<ButtonSize, string> = {
  md: 'min-h-10 px-3 text-sm',
  sm: 'min-h-9 px-2.5 text-sm',
  icon: 'h-10 w-10 p-0',
}

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  type = 'button',
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-[background-color,border-color,filter,transform] duration-[var(--wr-motion-control)] ease-out',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring',
        'disabled:cursor-not-allowed disabled:opacity-70',
        variantClass[variant],
        sizeClass[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
