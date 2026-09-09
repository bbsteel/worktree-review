import { useEffect, useState } from 'react'

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      return
    }

    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => {
      setReduced(media.matches)
    }

    media.addEventListener('change', onChange)
    return () => {
      media.removeEventListener('change', onChange)
    }
  }, [])

  return reduced
}

export function motionDurationSeconds(cssVariable: string, reduced: boolean, fallbackMs: number): number {
  if (reduced) {
    return 0
  }
  if (typeof window === 'undefined') {
    return fallbackMs / 1000
  }

  const raw = getComputedStyle(document.documentElement).getPropertyValue(cssVariable).trim()
  const ms = Number.parseFloat(raw)
  if (Number.isNaN(ms)) {
    return fallbackMs / 1000
  }
  return ms / 1000
}
