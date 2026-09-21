import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ThemeSwitcher } from '../components/ui/theme-switcher.tsx'
import { stubMatchMedia } from '../test/match-media.ts'
import { THEME_STORAGE_KEY } from './theme.ts'
import { ThemeProvider } from './ThemeProvider.tsx'

afterEach(() => {
  cleanup()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-theme-preference')
  window.localStorage.clear()
})

beforeEach(() => {
  window.localStorage.clear()
  stubMatchMedia({
    '(prefers-color-scheme: light)': false,
    '(prefers-reduced-motion: reduce)': false,
  })
})

describe('theme preference', () => {
  it('defaults to dark and persists a light choice', async ({ skip }) => {
    if (typeof window.localStorage === 'undefined') {
      skip()
    }

    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <ThemeSwitcher />
      </ThemeProvider>,
    )

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.dataset.themePreference).toBe('dark')

    await user.click(screen.getByRole('radio', { name: 'Light' }))

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(document.documentElement.dataset.themePreference).toBe('light')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })

  it('resolves system preference from matchMedia', async () => {
    const media = stubMatchMedia({
      '(prefers-color-scheme: light)': true,
      '(prefers-reduced-motion: reduce)': false,
    })
    const user = userEvent.setup()

    render(
      <ThemeProvider>
        <ThemeSwitcher />
      </ThemeProvider>,
    )

    await user.click(screen.getByRole('radio', { name: 'System' }))
    expect(document.documentElement.dataset.themePreference).toBe('system')
    expect(document.documentElement.dataset.theme).toBe('light')

    media.set('(prefers-color-scheme: light)', false)
    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe('dark')
    })
  })

  it('restores the stored preference on a later mount', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light')

    render(
      <ThemeProvider>
        <ThemeSwitcher />
      </ThemeProvider>,
    )

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(screen.getByRole('radio', { name: 'Light' })).toHaveAttribute('aria-checked', 'true')
  })
})
