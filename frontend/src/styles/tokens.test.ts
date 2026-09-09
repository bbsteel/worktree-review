import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  MOTION_TOKENS,
  RADIUS_TOKENS,
  SEMANTIC_COLOR_TOKENS,
  SPACING_TOKENS,
  TYPE_TOKENS,
} from './token-names.ts'

const css = readFileSync(path.resolve('src/styles/tokens.css'), 'utf8')

describe('semantic tokens', () => {
  it('defines color, spacing, type, radius, and motion tokens', () => {
    for (const token of [
      ...SEMANTIC_COLOR_TOKENS,
      ...SPACING_TOKENS,
      ...RADIUS_TOKENS,
      ...TYPE_TOKENS,
      ...MOTION_TOKENS,
    ]) {
      expect(css).toContain(`--wr-${token}`)
    }
  })

  it('sets distinct blocked and error colors in both themes', () => {
    expect(css).toMatch(/\[data-theme='dark'\][\s\S]*--wr-status-blocked: #ff755f/)
    expect(css).toMatch(/\[data-theme='dark'\][\s\S]*--wr-status-error: #ff5c7a/)
    expect(css).toMatch(/\[data-theme='light'\][\s\S]*--wr-status-blocked: #d84a32/)
    expect(css).toMatch(/\[data-theme='light'\][\s\S]*--wr-status-error: #c52345/)
  })

  it('zeroes motion tokens under reduced-motion', () => {
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).toContain('--wr-motion-dialog: 0ms')
  })
})
