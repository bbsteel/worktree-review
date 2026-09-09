import { expect, test } from '@playwright/test'

test('Overview route is reachable', async ({ page }) => {
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
})

test('root redirects to Overview', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/overview$/)
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
})

// The /reviews/:attemptId route is exercised end to end by review-detail.spec.ts
// (wired by PM-010); this file only covers the foundation-level routes above.
