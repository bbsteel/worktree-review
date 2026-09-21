/**
 * Live acceptance E2E (blockers 1–5, 7): a real browser drives a real server
 * over a fresh SQLite database through registration → policy/profile binding →
 * review creation → SSE progress → Passed/Blocked/Error terminal states →
 * reload persistence → Session Journal → Session Insight deep link.
 *
 * Run with: npx playwright test --config playwright.live.config.ts
 */
import { expect, test } from '@playwright/test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { setControlMode, startLiveFixture, type LiveFixture } from './live-fixture.ts'

test.describe.configure({ mode: 'serial' })

let fixture: LiveFixture

test.beforeAll(async () => {
  fixture = await startLiveFixture()
})

test.afterAll(async () => {
  await fixture?.cleanup()
})

test('fresh live server serves the production UI without mock badge', async ({ page }) => {
  await page.goto(`${fixture.baseUrl}/overview`)
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await expect(page.getByText('Mock data')).toHaveCount(0)
  // The shell reports the live local API, not the prototype mock.
  await expect(page.getByText(/live local API/)).toBeVisible()
})

test('register repository, profile, and trusted policies through the browser', async ({
  page,
}) => {
  await page.goto(`${fixture.baseUrl}/repositories`)
  await page.getByLabel('Repository path').fill(fixture.repositoryDir)
  await page.getByLabel('Display name (optional)').fill('live-fixture')
  await page.getByRole('button', { name: 'Register repository' }).click()
  await expect(page.getByRole('heading', { name: 'live-fixture' })).toBeVisible()

  await page.goto(`${fixture.baseUrl}/providers`)
  await page.getByRole('radio', { name: 'Local CLI' }).click()
  await expect(page.getByRole('radio', { name: 'Local CLI' })).toBeChecked()
  await page.getByLabel('Name').fill('fixture-local-cli')
  await page.getByLabel('Adapter', { exact: true }).fill('worktree-json')
  await page.getByLabel(/Command argv/).fill(fixture.reviewerArgv.join('\n'))
  await page.getByRole('button', { name: 'Create profile' }).click()
  await expect(page.getByRole('heading', { name: 'fixture-local-cli' })).toBeVisible()

  // Honest test-connection scope: executable resolution, not a fake call.
  await page.getByRole('button', { name: 'Test connection' }).click()
  await page.getByRole('button', { name: 'Run test' }).click()
  await expect(page.getByText(/local CLI executable check/)).toBeVisible()

  await page.goto(`${fixture.baseUrl}/policies`)
  await page.getByLabel('Trusted policy file path').fill(fixture.reviewPolicyPath)
  await page.getByRole('button', { name: 'Register Review Policy' }).click()
  await expect(page.getByText(/Registered trusted Review Policy/)).toBeVisible()

  await page.getByRole('tab', { name: 'Compute Policies' }).click()
  // Scope to the compute form: both tabs keep a "Trusted policy file path"
  // field in the DOM, and an unscoped getByLabel fills the Review Policy
  // input while Compute stays empty (submit remains disabled).
  const computeForm = page.getByRole('form', { name: 'Register trusted Compute Policy' })
  await computeForm.getByLabel('Trusted policy file path').fill(fixture.userConfigPath)
  await computeForm.getByLabel('Bound Provider Profile').selectOption({ index: 1 })
  await expect(computeForm.getByRole('button', { name: 'Register Compute Policy' })).toBeEnabled()
  await computeForm.getByRole('button', { name: 'Register Compute Policy' }).click()
  await expect(page.getByText(/Registered trusted Compute Policy/)).toBeVisible()
  await expect(page.getByText(/Not bound — reviews using this policy/)).toHaveCount(0)
})

async function startReview(page: import('@playwright/test').Page): Promise<string> {
  await page.goto(`${fixture.baseUrl}/reviews/new`)
  await page.getByLabel('Authorized repository').selectOption({ index: 1 })
  await page.getByLabel(/Trusted Review Policy/).selectOption({ index: 1 })
  await page.getByLabel(/Trusted Compute Policy/).selectOption({ index: 1 })
  await page.getByRole('button', { name: 'Start review' }).click()
  await page.waitForURL((url) => /\/reviews\/(?!new$)[^/]+$/.test(url.pathname))
  return page.url().split('/').pop() as string
}

test('passed review: SSE progress, terminal state, reload persistence', async ({
  page,
  request,
}) => {
  setControlMode(fixture.controlPath, 'pass')
  const attemptId = await startReview(page)

  // The attempt is queryable through the API within 1 second of creation.
  const queriedAt = Date.now()
  const queried = await request.get(`${fixture.baseUrl}/api/v1/reviews/${attemptId}`)
  expect(queried.ok()).toBeTruthy()
  expect(Date.now() - queriedAt).toBeLessThan(1000)

  // SSE drives the page to the real terminal state without a reload.
  await expect(page.getByText('Passed').first()).toBeVisible({ timeout: 30_000 })

  await page.reload()
  await expect(page.getByText('Passed').first()).toBeVisible()

  // The Session Journal holds the same Attempt ID.
  const metadataPath = path.join(fixture.journalRoot, attemptId, 'metadata.json')
  expect(fs.existsSync(metadataPath)).toBeTruthy()
  const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8')) as { attempt_id: string }
  expect(metadata.attempt_id).toBe(attemptId)
  expect(
    fs.existsSync(path.join(fixture.journalRoot, attemptId, 'result.json')),
  ).toBeTruthy()
})

test('blocked review: real finding with evidence reaches the gate', async ({ page }) => {
  setControlMode(fixture.controlPath, 'block')
  const attemptId = await startReview(page)
  await expect(page.getByText('Blocked').first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole('tab', { name: 'Findings' }).click()
  await expect(
    page.getByText('README contains a placeholder line that must not ship.').first(),
  ).toBeVisible()
  expect(attemptId).toBeTruthy()
})

test('error review: provider failure produces a real Error terminal state', async ({
  page,
}) => {
  setControlMode(fixture.controlPath, 'fail')
  await startReview(page)
  await expect(page.getByText('Error').first()).toBeVisible({ timeout: 30_000 })
})

test('session insight connected state and deep link from trusted config', async ({
  page,
}) => {
  setControlMode(fixture.controlPath, 'pass')
  const attemptId = await startReview(page)
  await expect(page.getByText('Passed').first()).toBeVisible({ timeout: 30_000 })
  const link = page.getByRole('link', { name: /Open Session Insight/ })
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute(
    'href',
    `${fixture.sessionInsightUrl}/#/session/worktree-review/${attemptId}`,
  )
})
