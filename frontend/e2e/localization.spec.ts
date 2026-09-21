import { expect, test } from '@playwright/test'

test('switches the web UI to Simplified Chinese', async ({ page }) => {
  await page.goto('/overview')

  const languageSelect = page.getByRole('combobox', { name: 'Language' })
  await expect(languageSelect).toBeVisible()
  await languageSelect.selectOption('zh-CN')

  await expect(page.getByRole('heading', { name: '概览' })).toBeVisible()
  await expect(page.getByText('需要关注 · 2')).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')

  await page.goto('/reviews/attempt_01JY8R7F2W?tab=findings')
  await expect(page.getByRole('tab', { name: '发现项' })).toBeVisible()
  await expect(page.getByRole('group', { name: '发现项筛选' })).toBeVisible()
})
