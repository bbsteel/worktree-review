import {
  Cable,
  FolderGit2,
  GitPullRequest,
  LayoutDashboard,
  Settings,
  Shield,
  Unplug,
} from 'lucide-react'
import { NavLink } from 'react-router'
import { useDataSource } from '../../app/data-source.ts'
import { PreviewControl } from '../ui/preview-control.tsx'
import { cx } from '../ui/cx.ts'

const previewReason = {
  reviews: 'Reviews list is Preview. Open a demo case from the prototype banner to see a Review Detail route.',
  sessionInsight: 'Session Insight is disconnected in this Pre-Alpha prototype.',
  github: 'GitHub integration is Preview and is not connected.',
  settings: 'Settings is Preview and is not available in this Pre-Alpha prototype.',
}

const NAV_LINK_CLASS =
  'inline-flex min-h-10 items-center gap-2 rounded-md px-2.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'

function navLinkClass(isActive: boolean): string {
  return cx(
    NAV_LINK_CLASS,
    isActive ? 'bg-surface-subtle text-text-primary' : 'text-text-secondary hover:text-text-primary',
  )
}

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const { overview, source } = useDataSource()
  const sessionState = overview?.sessionInsight.state ?? 'disconnected'

  return (
    <div className="flex h-full flex-col bg-surface text-text-primary">
      <div className="border-b border-border px-4 py-4">
        <p className="text-sm font-semibold tracking-tight">Worktree Review</p>
        <p className="mt-1 text-xs text-text-secondary">Evidence-first inspection</p>
      </div>
      <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 p-3">
        <NavLink
          to="/overview"
          onClick={onNavigate}
          className={({ isActive }) => navLinkClass(isActive)}
        >
          <LayoutDashboard aria-hidden="true" className="h-4 w-4" />
          Overview
        </NavLink>
        <PreviewControl label="Reviews" reason={previewReason.reviews} icon={GitPullRequest} />
        <NavLink
          to="/repositories"
          onClick={onNavigate}
          className={({ isActive }) => navLinkClass(isActive)}
        >
          <FolderGit2 aria-hidden="true" className="h-4 w-4" />
          Repositories
        </NavLink>
        <NavLink
          to="/policies"
          onClick={onNavigate}
          className={({ isActive }) => navLinkClass(isActive)}
        >
          <Shield aria-hidden="true" className="h-4 w-4" />
          Policies
        </NavLink>
        <NavLink
          to="/providers"
          onClick={onNavigate}
          className={({ isActive }) => navLinkClass(isActive)}
        >
          <Unplug aria-hidden="true" className="h-4 w-4" />
          Providers
        </NavLink>
        <p className="mt-3 px-2.5 text-[11px] uppercase tracking-wide text-text-secondary">Integrations</p>
        <PreviewControl
          label="Session Insight"
          reason={`${previewReason.sessionInsight} State: ${sessionState}.`}
          icon={Cable}
        />
        <PreviewControl label="GitHub" reason={previewReason.github} icon={GitPullRequest} />
        <div className="mt-auto">
          <PreviewControl label="Settings" reason={previewReason.settings} icon={Settings} />
        </div>
      </nav>
      <div className="border-t border-border px-4 py-3 text-xs text-text-secondary">
        <p>Web service: {source.kind === 'mock' ? 'prototype mock' : 'live local API'}</p>
        <p>Version 0.0.0 · Local</p>
        <p>Session Insight: {sessionState}</p>
      </div>
    </div>
  )
}
