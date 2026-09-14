/**
 * P0.5 stability matrix, browser level: system theme following, reduced
 * motion, and long-value layout integrity. Runs against the demo bundle.
 */
import { expect, test } from '@playwright/test'

const BLOCKED_ATTEMPT = 'attempt_01JY8R7F2W'
const ERROR_ATTEMPT = 'attempt_01JY8E4R0R'

test('system theme follows the emulated OS preference', async ({ page }) => {
  await page.goto('/overview')
  await page.getByRole('radio', { name: 'System' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme-preference', 'system')

  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

  // An explicit choice still wins over the OS.
  await page.getByRole('radio', { name: 'Light' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('reduced motion is honored on the detail pipeline animation', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(`/reviews/${BLOCKED_ATTEMPT}`)
  await expect(page.getByRole('heading', { name: 'acme/payment-service · PR #184' })).toBeVisible()
  // The reduced-motion contract: status is never conveyed by motion alone —
  // gate and pipeline nodes keep icon + text. (Framer animations are disabled
  // via the motion token path; the static status text must exist regardless.)
  await expect(page.locator('main').getByText('Blocked').first()).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Overview' })).toBeVisible()
})

test('long paths, SHAs and error text never break the layout at 1280px', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/reviews/${BLOCKED_ATTEMPT}`)
  await expect(page.getByRole('heading', { name: 'acme/payment-service · PR #184' })).toBeVisible()
  await page.getByRole('tab', { name: 'Findings' }).click()
  await expect(page.getByRole('tab', { name: 'Findings' })).toBeVisible()
  // No horizontal page scroll with long fingerprints/paths rendered.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
  await page.getByRole('tab', { name: 'Attempts' }).click()
  const overflowAttempts = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflowAttempts).toBeLessThanOrEqual(1)
})

test('merge-conflict error case renders safe detail, never a blank page', async ({ page }) => {
  await page.goto(`/reviews/${ERROR_ATTEMPT}`)
  await expect(page.locator('main').getByText('Error').first()).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})
