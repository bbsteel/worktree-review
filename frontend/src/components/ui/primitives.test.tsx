import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { stubMatchMedia } from '../../test/match-media.ts'
import { Badge } from './badge.tsx'
import { Button } from './button.tsx'
import { Dialog } from './dialog.tsx'
import { EmptyState } from './empty-state.tsx'
import { Skeleton } from './skeleton.tsx'
import { Tab, TabList, TabPanel, Tabs } from './tabs.tsx'
import { Tooltip } from './tooltip.tsx'

afterEach(() => {
  cleanup()
})

beforeEach(() => {
  stubMatchMedia({
    '(prefers-color-scheme: light)': false,
    '(prefers-reduced-motion: reduce)': false,
  })
})

function TabsExample() {
  const [value, setValue] = useState('overview')
  return (
    <Tabs value={value} onValueChange={setValue}>
      <TabList aria-label="Review sections">
        <Tab value="overview">Overview</Tab>
        <Tab value="findings">Findings</Tab>
      </TabList>
      <TabPanel value="overview">Overview panel</TabPanel>
      <TabPanel value="findings">Findings panel</TabPanel>
    </Tabs>
  )
}

function DialogExample() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open dialog</Button>
      <Dialog open={open} title="Confirm retry" description="Creates a new attempt." onClose={() => setOpen(false)}>
        <p>Dialog body</p>
      </Dialog>
    </>
  )
}

describe('ui primitives', () => {
  it('exposes a clear focus-visible ring class on Button', () => {
    render(<Button>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' }).className).toContain('focus-visible:outline-focus-ring')
  })

  it('renders status badges with icon and text, not color alone', () => {
    render(
      <>
        <Badge tone="blocked" label="Blocked" />
        <Badge tone="error" label="Error" />
        <Badge tone="passed" label="Passed" />
      </>,
    )

    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Error')).toBeInTheDocument()
    expect(screen.getByText('Passed')).toBeInTheDocument()
    expect(document.querySelectorAll('svg').length).toBeGreaterThanOrEqual(3)
  })

  it('moves between tabs with arrow keys', async () => {
    const user = userEvent.setup()
    render(<TabsExample />)

    expect(screen.getByText('Overview panel')).toBeInTheDocument()
    await user.tab()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Findings' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Findings panel')).toBeInTheDocument()
  })

  it('shows a tooltip on keyboard focus', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip content="Copy fingerprint">
        <Button>Fingerprint</Button>
      </Tooltip>,
    )

    await user.tab()
    expect(screen.getByRole('tooltip', { name: 'Copy fingerprint' })).toBeInTheDocument()
  })

  it('opens a dialog and closes it with Escape', async () => {
    const user = userEvent.setup()
    render(<DialogExample />)

    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    expect(screen.getByRole('dialog', { name: 'Confirm retry' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('disables skeleton pulse when reduced-motion is requested', () => {
    stubMatchMedia({
      '(prefers-color-scheme: light)': false,
      '(prefers-reduced-motion: reduce)': true,
    })

    render(<Skeleton className="h-4 w-24" />)
    const skeleton = screen.getByRole('status')
    expect(skeleton).toHaveAttribute('data-reduced-motion', 'true')
    expect(skeleton.className).not.toContain('animate-pulse')
  })

  it('renders an empty state with title and description', () => {
    render(<EmptyState title="No reviews" description="There are no attempts in this filter." />)
    expect(screen.getByRole('heading', { name: 'No reviews' })).toBeInTheDocument()
    expect(screen.getByText('There are no attempts in this filter.')).toBeInTheDocument()
  })
})
