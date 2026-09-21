import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

process.env.PLAYWRIGHT_BROWSERS_PATH ??= fileURLToPath(
  new URL('./.playwright-browsers', import.meta.url),
)

export default defineConfig({
  testDir: './e2e',
  // The live acceptance suite has its own config (playwright.live.config.ts):
  // it drives a real server and needs the live bundle, not this demo preview.
  testIgnore: 'live/**',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
  },
  webServer: {
    // E2E exercises the offline demo cases: build the explicit demo bundle.
    command: 'npm run build:demo && npm run preview -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
