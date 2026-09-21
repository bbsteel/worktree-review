import { Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Outlet } from 'react-router'
import { useDataSource } from '../../app/data-source.ts'
import { useI18n } from '../../i18n.tsx'
import { Button } from '../ui/button.tsx'
import { EmptyState } from '../ui/empty-state.tsx'
import { PrototypeBanner } from './PrototypeBanner.tsx'
import { SideNav } from './SideNav.tsx'
import { TopBar } from './TopBar.tsx'

export function ApplicationShell() {
  const [navOpen, setNavOpen] = useState(false)
  const { t } = useI18n()
  const { authSession } = useDataSource()

  // Authorized deployment without a verified session: the wall replaces the
  // entire app — no protected data is fetched or rendered (P3 §4.1).
  if (authSession !== null && authSession.mode === 'github-oauth' && !authSession.authenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-6 text-text-primary">
        <EmptyState
          title={t('Sign in required')}
          description={t(
            'This Worktree Review deployment requires a verified GitHub session. Reviews, audit logs, and policies are only visible after sign-in.',
          )}
        />
        <a
          href="/api/v1/auth/github/start"
          className="inline-flex min-h-10 items-center rounded-md bg-action-primary px-4 text-sm font-medium text-background transition-[filter] duration-[var(--wr-motion-control)] hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          {t('Sign in with GitHub')}
        </a>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-text-primary">
      <PrototypeBanner />
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-60 shrink-0 border-r border-border lg:block">
          <SideNav />
        </aside>
        {navOpen ? (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button
              type="button"
              aria-label={t('Close navigation overlay')}
              className="absolute inset-0 bg-[rgb(8_14_22_/_0.48)]"
              onClick={() => setNavOpen(false)}
            />
            <div className="relative h-full w-60 border-r border-border bg-surface">
              <div className="flex justify-end p-2">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t('Close navigation')}
                  onClick={() => setNavOpen(false)}
                >
                  <X aria-hidden="true" className="h-4 w-4" />
                </Button>
              </div>
              <SideNav onNavigate={() => setNavOpen(false)} />
            </div>
          </div>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-border bg-surface lg:border-b-0">
            <div className="pl-2 lg:hidden">
              <Button
                variant="ghost"
                size="icon"
                aria-label={t('Open navigation')}
                aria-expanded={navOpen}
                onClick={() => setNavOpen(true)}
              >
                <Menu aria-hidden="true" className="h-4 w-4" />
              </Button>
            </div>
            <div className="min-w-0 flex-1">
              <TopBar />
            </div>
          </div>
          <div className="min-h-0 min-w-0 flex-1 overflow-auto">
            <Outlet />
          </div>
        </div>
      </div>
    </div>
  )
}
