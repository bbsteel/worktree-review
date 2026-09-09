import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  applyTheme,
  persistThemePreference,
  readStoredThemePreference,
  resolveTheme,
  ThemeContext,
  type ThemePreference,
} from './theme.ts'

interface ThemeProviderProps {
  children: ReactNode
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredThemePreference)
  const [systemIsLight, setSystemIsLight] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false
    }
    return window.matchMedia('(prefers-color-scheme: light)').matches
  })

  const resolved = resolveTheme(preference, systemIsLight)

  useEffect(() => {
    applyTheme(preference, resolved)
    persistThemePreference(preference)
  }, [preference, resolved])

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      return
    }

    const media = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = (event: MediaQueryListEvent) => {
      setSystemIsLight(event.matches)
    }

    media.addEventListener('change', onChange)
    return () => {
      media.removeEventListener('change', onChange)
    }
  }, [])

  const value = useMemo(
    () => ({
      preference,
      resolved,
      setPreference: setPreferenceState,
    }),
    [preference, resolved],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
