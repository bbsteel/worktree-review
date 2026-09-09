import { useEffect, useState } from 'react'
import { useAdminClient } from '../app/admin-client.ts'
import { Badge } from '../components/ui/badge.tsx'
import { Button } from '../components/ui/button.tsx'
import { Dialog } from '../components/ui/dialog.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import type { RepositoryDto, RepositoryStatusDto } from '../data/api/dto.ts'
import { ApiError } from '../data/api/review-api-client.ts'
import { formatTimestamp } from '../features/review-detail/formatting.ts'
import { GATE_PRESENTATION } from '../features/review-detail/presentation.ts'
import { CopyValue } from '../features/review-detail/CopyValue.tsx'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'

/**
 * Repositories page (design 11.6): local path authorization and visibility.
 * Removing authorization never deletes repository content or review history.
 */
export function RepositoriesPage() {
  const client = useAdminClient()
  const [repositories, setRepositories] = useState<RepositoryDto[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusById, setStatusById] = useState<Record<string, RepositoryStatusDto | 'unavailable'>>({})
  const [path, setPath] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [registering, setRegistering] = useState(false)
  const [registerError, setRegisterError] = useState<string | null>(null)
  const [pendingRemoval, setPendingRemoval] = useState<RepositoryDto | null>(null)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    client
      .listRepositories()
      .then((list) => {
        if (cancelled) {
          return
        }
        setRepositories(list)
        for (const repository of list) {
          client
            .getRepositoryStatus(repository.repository_id)
            .then((status) => {
              if (!cancelled) {
                setStatusById((current) => ({ ...current, [repository.repository_id]: status }))
              }
            })
            .catch(() => {
              if (!cancelled) {
                setStatusById((current) => ({
                  ...current,
                  [repository.repository_id]: 'unavailable',
                }))
              }
            })
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(
            caught instanceof Error ? caught.message : 'Repositories could not be loaded.',
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [client])

  async function register() {
    if (path.trim() === '') {
      setRegisterError('A repository path is required.')
      return
    }
    setRegistering(true)
    setRegisterError(null)
    try {
      const registered = await client.registerRepository({
        path: path.trim(),
        ...(displayName.trim() === '' ? {} : { display_name: displayName.trim() }),
      })
      setRepositories((current) => [...(current ?? []), registered])
      setPath('')
      setDisplayName('')
      try {
        const status = await client.getRepositoryStatus(registered.repository_id)
        setStatusById((current) => ({ ...current, [registered.repository_id]: status }))
      } catch {
        setStatusById((current) => ({ ...current, [registered.repository_id]: 'unavailable' }))
      }
    } catch (caught) {
      setRegisterError(
        caught instanceof ApiError
          ? `${caught.code}: ${caught.message}`
          : 'The repository could not be registered. Nothing was changed.',
      )
    } finally {
      setRegistering(false)
    }
  }

  async function confirmRemoval() {
    if (pendingRemoval === null) {
      return
    }
    setRemoving(true)
    setRemoveError(null)
    try {
      await client.removeRepository(pendingRemoval.repository_id)
      setRepositories((current) =>
        (current ?? []).filter(
          (repository) => repository.repository_id !== pendingRemoval.repository_id,
        ),
      )
      setPendingRemoval(null)
    } catch (caught) {
      setRemoveError(
        caught instanceof ApiError
          ? `${caught.code}: ${caught.message}`
          : 'Authorization could not be removed.',
      )
    } finally {
      setRemoving(false)
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6">
        <EmptyState
          title="Repositories require the live review service"
          description={`The repository registry could not be loaded: ${loadError}. The prototype mock mode does not manage authorizations.`}
        />
      </main>
    )
  }

  if (repositories === null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-8 w-48" label="Loading repositories" />
        <Skeleton className="mt-4 h-48 w-full" label="Loading repository list" />
      </main>
    )
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-6">
      <h1 className="text-xl font-semibold text-text-primary">Repositories</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Local repository authorization and visibility. This page never modifies repository
        contents.
      </p>

      <section aria-label="Register repository" className="mt-4 rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">Add a local repository</h2>
        <p className="mt-1 text-meta text-text-secondary">
          The backend resolves and validates the real root. Only explicitly registered paths can be
          reviewed; symlink drift is re-checked on every run.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-meta text-text-secondary">
            Repository path
            <input
              type="text"
              value={path}
              onChange={(event) => {
                setPath(event.target.value)
                setRegisterError(null)
              }}
              className={FIELD_CLASS}
              placeholder="/home/you/projects/service"
            />
          </label>
          <label className="flex flex-col gap-1 text-meta text-text-secondary">
            Display name (optional)
            <input
              type="text"
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value)
              }}
              className={FIELD_CLASS}
              placeholder="acme/payment-service"
            />
          </label>
        </div>
        {registerError !== null ? (
          <p role="alert" className="mt-2 text-sm text-status-error">
            {registerError}
          </p>
        ) : null}
        <div className="mt-3">
          <Button
            variant="primary"
            size="sm"
            disabled={registering}
            onClick={() => {
              void register()
            }}
          >
            {registering ? 'Registering…' : 'Register repository'}
          </Button>
        </div>
      </section>

      <section aria-label="Authorized repositories" className="mt-4">
        {repositories.length === 0 ? (
          <EmptyState
            title="No authorized repositories"
            description="Register a local repository above to enable web-started reviews."
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {repositories.map((repository) => {
              const status = statusById[repository.repository_id]
              const statusRecord = status !== undefined && status !== 'unavailable' ? status : null
              const lastGate =
                repository.last_gate_state !== null &&
                repository.last_gate_state in GATE_PRESENTATION
                  ? GATE_PRESENTATION[
                      repository.last_gate_state as keyof typeof GATE_PRESENTATION
                    ]
                  : undefined
              return (
                <li
                  key={repository.repository_id}
                  className="rounded-lg border border-border bg-surface p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-text-primary">
                      {repository.display_name}
                    </h2>
                    {lastGate !== undefined ? (
                      <Badge tone={lastGate.tone} label={`Last gate: ${lastGate.label}`} />
                    ) : (
                      <Badge tone="neutral" label="No reviews yet" />
                    )}
                    {statusRecord !== null && statusRecord.dirty ? (
                      <Badge tone="warning" label="Worktree modified" />
                    ) : null}
                    {statusRecord !== null && !statusRecord.accessible ? (
                      <Badge tone="error" label="Not accessible" />
                    ) : null}
                    {statusRecord !== null && statusRecord.identity_drift ? (
                      <Badge tone="error" label="Identity drift detected" />
                    ) : null}
                    {status === 'unavailable' ? (
                      <Badge tone="warning" label="Status unavailable" />
                    ) : null}
                  </div>
                  <dl className="mt-2 grid grid-cols-1 gap-1 text-meta sm:grid-cols-2">
                    <div className="flex gap-1.5">
                      <dt className="shrink-0 text-text-secondary">Canonical root</dt>
                      <dd className="break-all font-mono text-text-primary">
                        {repository.canonical_root}
                      </dd>
                    </div>
                    {statusRecord !== null ? (
                      <>
                        <div className="flex gap-1.5">
                          <dt className="text-text-secondary">Branch</dt>
                          <dd className="font-mono text-text-primary">{statusRecord.branch}</dd>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <dt className="text-text-secondary">HEAD</dt>
                          <dd>
                            <CopyValue value={statusRecord.head_oid} label="HEAD OID" />
                          </dd>
                        </div>
                        <div className="flex gap-1.5">
                          <dt className="text-text-secondary">Changes</dt>
                          <dd className="text-text-primary">
                            {statusRecord.tracked_modifications} tracked ·{' '}
                            {statusRecord.untracked_files} untracked
                          </dd>
                        </div>
                      </>
                    ) : null}
                    {repository.last_reviewed_at !== null ? (
                      <div className="flex gap-1.5">
                        <dt className="text-text-secondary">Last reviewed</dt>
                        <dd className="text-text-primary">
                          {formatTimestamp(repository.last_reviewed_at)}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                  <div className="mt-3 border-t border-border pt-3">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setPendingRemoval(repository)
                        setRemoveError(null)
                      }}
                    >
                      Remove authorization
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <Dialog
        open={pendingRemoval !== null}
        title="Remove repository authorization"
        description="This only removes web authorization. It does not delete the repository on disk or any review history."
        onClose={() => {
          if (!removing) {
            setPendingRemoval(null)
          }
        }}
      >
        {pendingRemoval !== null ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-text-primary">
              Stop authorizing{' '}
              <span className="font-mono">{pendingRemoval.display_name}</span> (
              <span className="break-all font-mono text-meta">
                {pendingRemoval.canonical_root}
              </span>
              ) for web-started reviews?
            </p>
            {removeError !== null ? (
              <p role="alert" className="text-sm text-status-error">
                {removeError}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={removing}
                onClick={() => {
                  setPendingRemoval(null)
                }}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={removing}
                onClick={() => {
                  void confirmRemoval()
                }}
              >
                {removing ? 'Removing…' : 'Remove authorization'}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </main>
  )
}
