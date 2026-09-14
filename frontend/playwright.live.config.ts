import { defineConfig, devices } from '@playwright/test'

/**
 * Live acceptance E2E: drives the real worktree-review-server over a fresh
 * SQLite database. The spec spawns the server itself (see e2e/live), so this
 * config has no webServer and does not rebuild the demo bundle — it requires
 * the LIVE production build (npm run build) in frontend/dist.
 */
export default defineConfig({
  testDir: './e2e/live',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 90_000,
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
