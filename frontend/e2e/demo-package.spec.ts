/**
 * PM-011 demo package screenshot capture.
 *
 * Captures the fixed frames referenced by the demo click script in
 * .ai-docs/WEB-UI-DEMO-PACKAGE.zh-CN.md. All frames use the dark default
 * theme at 1440x900 (the primary demo viewport; the full viewport/theme
 * matrix is covered by dashboard-qa.spec.ts).
 */
import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'

const BLOCKED_ATTEMPT = 'attempt_01JY8R7F2W'
const PASSED_ATTEMPT = 'attempt_01JY8P4SS0D'
const ERROR_ATTEMPT = 'attempt_01JY8E4R0R'

const OUTPUT_DIR = 'qa/pm011'

async function prepare(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('worktree-review.theme', 'dark')
  })
  await page.setViewportSize({ width: 1440, height: 900 })
}

async function capture(page: Page, name: string) {
  await page.screenshot({ path: path.resolve(OUTPUT_DIR, `${name}.png`), fullPage: true })
}

test('demo package: dashboard needs-attention frame', async ({ page }) => {
  await prepare(page)
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: /Needs attention/ })).toBeVisible()
  await expect(page.getByTestId('prototype-badge')).toHaveText('Mock data · Pre-Alpha')
  await capture(page, '01-dashboard-needs-attention')
})

test('demo package: blocked case overview frame', async ({ page }) => {
  await prepare(page)
  await page.goto(`/reviews/${BLOCKED_ATTEMPT}`)
  await expect(
    page.getByRole('heading', { name: 'acme/payment-service · PR #184' }),
  ).toBeVisible()
  await expect(page.locator('main').getByText('Blocked').first()).toBeVisible()
  await capture(page, '02-blocked-detail-overview')
})

test('demo package: blocked case findings and evidence frame', async ({ page }) => {
  await prepare(page)
  await page.goto(`/reviews/${BLOCKED_ATTEMPT}?tab=findings`)
  const blockingOnly = page.getByRole('checkbox', { name: 'Blocking only' })
  await blockingOnly.click()
  await expect(blockingOnly).toBeChecked()
  await expect(page.getByText('1 of 3 findings')).toBeVisible()
  await expect(
    page.getByRole('heading', { name: /fallback branch still accepts the webhook request/ }),
  ).toBeVisible()
  await capture(page, '03-blocked-findings-evidence')
})

test('demo package: blocked case attempts frame', async ({ page }) => {
  await prepare(page)
  await page.goto(`/reviews/${BLOCKED_ATTEMPT}?tab=attempts`)
  await expect(page.getByText('Current attempt', { exact: true })).toBeVisible()
  await capture(page, '04-blocked-attempts')
})

test('demo package: passed local case frame', async ({ page }) => {
  await prepare(page)
  await page.goto(`/reviews/${PASSED_ATTEMPT}`)
  await expect(page.getByRole('heading', { name: 'acme/session-insight' })).toBeVisible()
  await expect(page.getByText('Local one-shot result')).toBeVisible()
  await capture(page, '05-passed-local-detail')
})

test('demo package: error merge-conflict case frame', async ({ page }) => {
  await prepare(page)
  await page.goto(`/reviews/${ERROR_ATTEMPT}`)
  await expect(page.locator('main').getByText('Error').first()).toBeVisible()
  await expect(page.getByText(/Run status: Failed/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Bypass' })).toHaveCount(0)
  await capture(page, '06-error-merge-conflict-detail')
})
