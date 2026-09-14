/**
 * Review Detail browser scenarios (B-015).
 *
 * The /reviews/:attemptId route was assembled by PM-010; these specs exercise
 * the real page end to end inside the Application Shell. Text assertions are
 * scoped to <main> so the demo case selector <option> labels in the shell
 * banner (which repeat gate words like "Blocked"/"Error") cannot shadow them.
 */
import { expect, test, type Page } from '@playwright/test'

const BLOCKED_ATTEMPT = 'attempt_01JY8R7F2W'
const PASSED_ATTEMPT = 'attempt_01JY8P4SS0D'
const ERROR_ATTEMPT = 'attempt_01JY8E4R0R'

async function gotoDetail(page: Page, attemptId: string) {
  await page.goto(`/reviews/${attemptId}`)
}

test.describe('review detail', () => {
  test('blocked case shows gate, tabs and source-adaptive header', async ({ page }) => {
    await gotoDetail(page, BLOCKED_ATTEMPT)

    await expect(page.getByRole('heading', { name: 'acme/payment-service · PR #184' })).toBeVisible()
    await expect(page.getByText('Harden webhook authorization')).toBeVisible()
    await expect(page.locator('main').getByText('Blocked').first()).toBeVisible()
    await expect(page.getByText('Authoritative attempt')).toBeVisible()

    for (const label of [
      'Overview',
      'Findings',
      'Coverage',
      'Attempts',
      'Identity & Provenance',
      'Policies',
      'Usage',
    ]) {
      await expect(page.getByRole('tab', { name: label })).toBeVisible()
    }
  })

  test('finding filter leads to evidence', async ({ page }) => {
    await gotoDetail(page, `${BLOCKED_ATTEMPT}?tab=findings`)

    // click + auto-retrying assertion: React Router commits the URL update
    // asynchronously, so a bare .check() post-click state read is racy
    // under parallel load.
    const blockingOnly = page.getByRole('checkbox', { name: 'Blocking only' })
    await blockingOnly.click()
    await expect(blockingOnly).toBeChecked()
    await expect(page.getByText('1 of 3 findings')).toBeVisible()
    await expect(
      page.getByRole('heading', { name: /fallback branch still accepts the webhook request/ }),
    ).toBeVisible()
    await expect(page.getByText(/signature header missing; accepting for compatibility/)).toBeVisible()
  })

  test('coverage, attempts and identity tabs render their core content', async ({ page }) => {
    await gotoDetail(page, BLOCKED_ATTEMPT)

    await page.getByRole('tab', { name: 'Coverage' }).click()
    await expect(page.getByText('Required Coverage')).toBeVisible()
    await expect(page.locator('main').getByText('Complete').first()).toBeVisible()

    await page.getByRole('tab', { name: 'Attempts' }).click()
    await expect(page.getByText('Current attempt', { exact: true })).toBeVisible()

    await page.getByRole('tab', { name: 'Identity & Provenance' }).click()
    await expect(page.getByText('github:acme/payment-service#184')).toBeVisible()
  })

  test('retry and bypass show capability and disabled reasons, no remote request', async ({
    page,
  }) => {
    const remoteRequests: string[] = []
    page.on('request', (request) => {
      const url = request.url()
      if (!url.startsWith('http://127.0.0.1')) {
        remoteRequests.push(url)
      }
    })

    await gotoDetail(page, BLOCKED_ATTEMPT)

    await expect(page.getByRole('button', { name: 'Retry' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Bypass' })).toBeDisabled()
    await expect(page.getByLabel(/Bypass unavailable:/)).toBeVisible()
    expect(remoteRequests).toEqual([])
  })

  test('error case never shows a bypass action', async ({ page }) => {
    await gotoDetail(page, ERROR_ATTEMPT)

    await expect(page.locator('main').getByText('Error').first()).toBeVisible()
    await expect(page.getByText(/Run status: Failed/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Bypass' })).toHaveCount(0)
    await page.getByRole('tab', { name: 'Identity & Provenance' }).click()
    await expect(
      page.getByText('Review identity unavailable — merge candidate was not constructed.'),
    ).toBeVisible()
  })

  test('passed local case shows one-shot identity without PR fields', async ({ page }) => {
    await gotoDetail(page, PASSED_ATTEMPT)

    await expect(page.getByRole('heading', { name: 'acme/session-insight' })).toBeVisible()
    await expect(page.getByText('Local one-shot result')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Bypass' })).toHaveCount(0)
  })

  test('light theme applies to the detail page', async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('worktree-review.theme', 'light')
    })
    await gotoDetail(page, BLOCKED_ATTEMPT)

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await expect(page.locator('main').getByText('Blocked').first()).toBeVisible()
  })
})
