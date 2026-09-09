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
  repositories: 'Repository registration is Preview and is not available in this Pre-Alpha prototype.',
  policies: 'Policy registry is Preview and is not available in this Pre-Alpha prototype.',
  providers: 'Provider profile management is Preview and is not available in this Pre-Alpha prototype.',
  sessionInsight: 'Session Insight is disconnected in this Pre-Alpha prototype.',
  github: 'GitHub integration is Preview and is not connected.',
  settings: 'Settings is Preview and is not available in this Pre-Alpha prototype.',
}

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const { overview } = useDataSource()
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
          className={({ isActive }) =>
            cx(
              'inline-flex min-h-10 items-center gap-2 rounded-md px-2.5 text-sm',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring',
              isActive ? 'bg-surface-subtle text-text-primary' : 'text-text-secondary hover:text-text-primary',
            )
          }
        >
          <LayoutDashboard aria-hidden="true" className="h-4 w-4" />
          Overview
        </NavLink>
        <PreviewControl label="Reviews" reason={previewReason.reviews} icon={GitPullRequest} />
        <PreviewControl label="Repositories" reason={previewReason.repositories} icon={FolderGit2} />
        <PreviewControl label="Policies" reason={previewReason.policies} icon={Shield} />
        <PreviewControl label="Providers" reason={previewReason.providers} icon={Unplug} />
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
        <p>Web service: prototype mock</p>
        <p>Version 0.0.0 · Local</p>
        <p>Session Insight: {sessionState}</p>
      </div>
    </div>
  )
}
