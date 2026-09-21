import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'

const viewports = [
  { name: '1280x800', width: 1280, height: 800 },
  { name: '1366x768', width: 1366, height: 768 },
  { name: '1440x900', width: 1440, height: 900 },
] as const

async function setTheme(page: Page, theme: 'dark' | 'light') {
  await page.addInitScript((value) => {
    window.localStorage.setItem('worktree-review.theme', value)
  }, theme)
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement
    return root.scrollWidth > root.clientWidth + 1
  })
  expect(overflow).toBe(false)
}

async function contrastRatio(page: Page): Promise<number> {
  return page.evaluate(() => {
    function parseColor(value: string): [number, number, number] {
      const rgb = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
      if (!rgb) {
        return [0, 0, 0]
      }
      return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]
    }
    function luminance([r, g, b]: [number, number, number]): number {
      const channel = [r, g, b].map((part) => {
        const scaled = part / 255
        return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * channel[0] + 0.7152 * channel[1] + 0.0722 * channel[2]
    }
    const body = getComputedStyle(document.body)
    const fg = luminance(parseColor(body.color))
    const bg = luminance(parseColor(body.backgroundColor))
    const lighter = Math.max(fg, bg)
    const darker = Math.min(fg, bg)
    return (lighter + 0.05) / (darker + 0.05)
  })
}

for (const viewport of viewports) {
  for (const theme of ['dark', 'light'] as const) {
    test(`Overview ${theme} ${viewport.name} does not overflow and keeps readable contrast`, async ({
      page,
    }, testInfo) => {
      await setTheme(page, theme)
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto('/overview')
      await expect(page.getByRole('heading', { name: /Needs attention/ })).toBeVisible()
      await assertNoHorizontalOverflow(page)
      expect(await contrastRatio(page)).toBeGreaterThanOrEqual(7)
      const screenshotPath = path.join(
        testInfo.project.outputDir,
        `overview-${theme}-${viewport.name}.png`,
      )
      await page.screenshot({
        path: path.resolve('qa/a014', `overview-${theme}-${viewport.name}.png`),
        fullPage: true,
      })
      await page.screenshot({ path: screenshotPath, fullPage: true })
    })
  }
}

test('Dashboard keyboard can reach a Needs Attention review', async ({ page }) => {
  await setTheme(page, 'dark')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: /Needs attention/ })).toBeVisible()

  let reached = false
  for (let index = 0; index < 40; index += 1) {
    await page.keyboard.press('Tab')
    const href = await page.evaluate(() => document.activeElement?.getAttribute('href'))
    if (href?.startsWith('/reviews/')) {
      reached = true
      break
    }
  }
  expect(reached).toBe(true)
})
