import { expect, test } from '@playwright/test'

test('Overview empty route is reachable', async ({ page }) => {
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
})

test('root redirects to Overview', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/overview$/)
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
})

test('Review Detail empty route is reachable', async ({ page }) => {
  await page.goto('/reviews/attempt_01JY8R7F2W')
  await expect(page.getByRole('heading', { name: 'Review Detail' })).toBeVisible()
  await expect(page.getByTestId('attempt-id')).toHaveTextContent('attempt_01JY8R7F2W')
})
