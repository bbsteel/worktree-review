import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { useAdminClient } from '../app/admin-client.ts'
import { Button } from '../components/ui/button.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import type {
  ComputePolicyDto,
  ProviderProfileDto,
  RepositoryDto,
  RepositoryStatusDto,
  ReviewPolicyDto,
} from '../data/api/dto.ts'
import { ApiError, IdempotencyConflictError } from '../data/api/review-api-client.ts'
import {
  buildCreateReviewRequest,
  describeSourceSelection,
  INITIAL_NEW_REVIEW_FORM,
  newIdempotencyKey,
  validateNewReviewForm,
  type NewReviewFormErrors,
  type NewReviewFormState,
  type ReviewSourceMode,
} from '../features/new-review/new-review-form.ts'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'
const ERROR_CLASS = 'mt-1 text-meta text-status-error'

interface LoadedCatalog {
  repositories: RepositoryDto[]
  reviewPolicies: ReviewPolicyDto[]
  computePolicies: ComputePolicyDto[]
  providerProfiles: ProviderProfileDto[]
}

function Section({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="rounded-lg border border-border bg-surface p-4">
      <legend className="px-1 text-sm font-semibold text-text-primary">{legend}</legend>
      <div className="flex flex-col gap-3">{children}</div>
    </fieldset>
  )
}

function FieldError({ message }: { message: string | undefined }) {
  return message !== undefined ? <p className={ERROR_CLASS}>{message}</p> : null
}

const SOURCE_MODE_LABEL: Record<ReviewSourceMode, string> = {
  'local-worktree': 'Current worktree',
  'local-recent-commits': 'Recent commits + worktree',
  'local-committed-ref': 'Committed ref',
}

/**
 * New Review (design 11): a sectioned single-page form. Before submission
 * the user sees repository, source, policies, provider/model, data
 * destination, retention and budget in one confirmation block. Submission
 * uses a stable Idempotency-Key, so a retry of the same submission cannot
 * create a duplicate attempt.
 */
export function NewReviewPage() {
  const client = useAdminClient()
  const navigate = useNavigate()

  const [catalog, setCatalog] = useState<LoadedCatalog | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [form, setForm] = useState<NewReviewFormState>(INITIAL_NEW_REVIEW_FORM)
  const [errors, setErrors] = useState<NewReviewFormErrors>({})
  const [repositoryStatusResult, setRepositoryStatusResult] = useState<{
    repositoryId: string
    status: RepositoryStatusDto | null
  } | null>(null)
  const [idempotencyKey] = useState(newIdempotencyKey)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      client.listRepositories(),
      client.listReviewPolicies(),
      client.listComputePolicies(),
      client.listProviderProfiles(),
    ])
      .then(([repositories, reviewPolicies, computePolicies, providerProfiles]) => {
        if (!cancelled) {
          setCatalog({ repositories, reviewPolicies, computePolicies, providerProfiles })
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(
            caught instanceof Error
              ? caught.message
              : 'Configuration could not be loaded from the review service.',
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [client])

  useEffect(() => {
    if (form.repositoryId === '') {
      return
    }
    let cancelled = false
    const repositoryId = form.repositoryId
    client
      .getRepositoryStatus(repositoryId)
      .then((status) => {
        if (!cancelled) {
          setRepositoryStatusResult({ repositoryId, status })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRepositoryStatusResult({ repositoryId, status: null })
        }
      })
    return () => {
      cancelled = true
    }
  }, [client, form.repositoryId])

  function update(patch: Partial<NewReviewFormState>) {
    setForm((current) => ({ ...current, ...patch }))
    setErrors({})
    setSubmitError(null)
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6">
        <EmptyState
          title="New Review requires the live review service"
          description={`Configuration could not be loaded: ${loadError}. The prototype mock mode does not create attempts.`}
        />
      </main>
    )
  }

  if (catalog === null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-8 w-48" label="Loading New Review" />
        <Skeleton className="mt-4 h-64 w-full" label="Loading configuration" />
      </main>
    )
  }

  const selectedComputePolicy =
    catalog.computePolicies.find((policy) => policy.policy_id === form.computePolicyId) ?? null
  const resolvedProfile =
    catalog.providerProfiles.find(
      (profile) => profile.profile_id === selectedComputePolicy?.provider_profile_id,
    ) ?? null
  const selectedReviewPolicy =
    catalog.reviewPolicies.find((policy) => policy.policy_id === form.reviewPolicyId) ?? null
  const selectedRepository =
    catalog.repositories.find((repository) => repository.repository_id === form.repositoryId) ??
    null
  const repositoryStatus =
    repositoryStatusResult !== null && repositoryStatusResult.repositoryId === form.repositoryId
      ? repositoryStatusResult.status
      : null
  const sourceSelection = describeSourceSelection(form)
  const committedRefDirty =
    form.sourceMode === 'local-committed-ref' && repositoryStatus?.dirty === true

  async function submit() {
    const nextErrors = validateNewReviewForm(form)
    if (committedRefDirty) {
      nextErrors.proposedRef =
        'Committed-ref reviews require a clean worktree; this repository has uncommitted changes.'
    }
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    try {
      const response = await client.createReview(buildCreateReviewRequest(form), idempotencyKey)
      await navigate(`/reviews/${response.attempt_id}`)
    } catch (caught) {
      if (caught instanceof IdempotencyConflictError) {
        setSubmitError(
          'This submission key was already used with different inputs. Reload the form to start a fresh submission.',
        )
      } else {
        setSubmitError(
          caught instanceof ApiError
            ? `${caught.code}: ${caught.message}`
            : 'The review could not be started. Nothing was created.',
        )
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-6">
      <h1 className="text-xl font-semibold text-text-primary">New Review</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Start one local, non-authoritative review attempt. All sections are visible before you
        start; nothing is hidden behind a wizard.
      </p>

      <form
        className="mt-4 flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <Section legend="Repository">
          {catalog.repositories.length === 0 ? (
            <EmptyState
              title="No authorized repositories"
              description="Register a local repository before starting a review. Browsers cannot browse your filesystem; only explicitly registered roots are accepted."
              action={
                <Link
                  to="/repositories"
                  className="text-sm text-action-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                >
                  Open Repositories
                </Link>
              }
            />
          ) : (
            <>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                Authorized repository
                <select
                  value={form.repositoryId}
                  onChange={(event) => {
                    update({ repositoryId: event.target.value })
                  }}
                  className={FIELD_CLASS}
                >
                  <option value="">Select a repository…</option>
                  {catalog.repositories.map((repository) => (
                    <option key={repository.repository_id} value={repository.repository_id}>
                      {repository.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <FieldError message={errors.repositoryId} />
              {selectedRepository !== null ? (
                <dl className="grid grid-cols-1 gap-1 text-meta sm:grid-cols-2">
                  <div className="flex gap-1.5">
                    <dt className="text-text-secondary">Root</dt>
                    <dd className="break-all font-mono text-text-primary">
                      {selectedRepository.canonical_root}
                    </dd>
                  </div>
                  {repositoryStatus !== null ? (
                    <>
                      <div className="flex gap-1.5">
                        <dt className="text-text-secondary">Branch</dt>
                        <dd className="font-mono text-text-primary">{repositoryStatus.branch}</dd>
                      </div>
                      <div className="flex gap-1.5">
                        <dt className="text-text-secondary">Worktree</dt>
                        <dd className="text-text-primary">
                          {repositoryStatus.dirty
                            ? `Modified — ${repositoryStatus.tracked_modifications} tracked, ${repositoryStatus.untracked_files} untracked`
                            : 'Clean'}
                        </dd>
                      </div>
                    </>
                  ) : null}
                </dl>
              ) : null}
            </>
          )}
        </Section>

        <Section legend="Review Source">
          <div role="radiogroup" aria-label="Review source" className="flex flex-col gap-2">
            {(Object.keys(SOURCE_MODE_LABEL) as ReviewSourceMode[]).map((mode) => (
              <label key={mode} className="flex min-h-9 items-center gap-2 text-sm text-text-primary">
                <input
                  type="radio"
                  name="review-source"
                  value={mode}
                  checked={form.sourceMode === mode}
                  onChange={() => {
                    update({ sourceMode: mode })
                  }}
                  className="h-4 w-4 accent-[var(--wr-action-primary)]"
                />
                {SOURCE_MODE_LABEL[mode]}
              </label>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {form.sourceMode !== 'local-recent-commits' ? (
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                Target ref (optional, defaults to HEAD)
                <input
                  type="text"
                  value={form.targetRef}
                  onChange={(event) => {
                    update({ targetRef: event.target.value })
                  }}
                  className={FIELD_CLASS}
                  placeholder="HEAD"
                />
              </label>
            ) : (
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                Commit count (N ≥ 0; target derives to HEAD~N)
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={form.commitCount}
                  onChange={(event) => {
                    update({ commitCount: event.target.value })
                  }}
                  className={FIELD_CLASS}
                  placeholder="3"
                />
              </label>
            )}

            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              Proposed
              <input
                type="text"
                value={
                  form.sourceMode === 'local-committed-ref' ? form.proposedRef : 'WORKTREE'
                }
                disabled={form.sourceMode !== 'local-committed-ref'}
                onChange={(event) => {
                  update({ proposedRef: event.target.value })
                }}
                className={FIELD_CLASS}
                placeholder="feature/my-change"
              />
            </label>
          </div>
          <FieldError message={errors.commitCount} />
          <FieldError message={errors.proposedRef} />
          {form.sourceMode === 'local-committed-ref' ? (
            <p className="text-meta text-text-secondary">
              The worktree must be clean for committed-ref reviews.
            </p>
          ) : null}
        </Section>

        <Section legend="Review Policy">
          <label className="flex flex-col gap-1 text-meta text-text-secondary">
            Trusted Review Policy (decides what is reviewed and the gate)
            <select
              value={form.reviewPolicyId}
              onChange={(event) => {
                update({ reviewPolicyId: event.target.value })
              }}
              className={FIELD_CLASS}
            >
              <option value="">Select a Review Policy…</option>
              {catalog.reviewPolicies.map((policy) => (
                <option key={policy.policy_id} value={policy.policy_id}>
                  {policy.name} {policy.version}
                  {policy.builtin ? ' (built-in)' : ''}
                </option>
              ))}
            </select>
          </label>
          <FieldError message={errors.reviewPolicyId} />
          {selectedReviewPolicy !== null ? (
            <dl className="grid grid-cols-1 gap-1 text-meta sm:grid-cols-2">
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">SHA-256</dt>
                <dd className="font-mono text-text-primary">
                  {selectedReviewPolicy.sha256.slice(0, 16)}…
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Required dimensions</dt>
                <dd className="font-mono text-text-primary">
                  {selectedReviewPolicy.required_dimensions.join(', ') || 'none'}
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Blocking severities</dt>
                <dd className="text-text-primary">
                  {selectedReviewPolicy.blocking_severities.join(', ')} (min evidence:{' '}
                  {selectedReviewPolicy.minimum_blocking_evidence_band})
                </dd>
              </div>
            </dl>
          ) : null}
        </Section>

        <Section legend="Compute Policy & Provider Profile">
          <label className="flex flex-col gap-1 text-meta text-text-secondary">
            Trusted Compute Policy (decides model, budget and call limits)
            <select
              value={form.computePolicyId}
              onChange={(event) => {
                update({ computePolicyId: event.target.value })
              }}
              className={FIELD_CLASS}
            >
              <option value="">Select a Compute Policy…</option>
              {catalog.computePolicies.map((policy) => (
                <option key={policy.policy_id} value={policy.policy_id}>
                  {policy.name} {policy.version} — {policy.provider} / {policy.model}
                </option>
              ))}
            </select>
          </label>
          <FieldError message={errors.computePolicyId} />
          {selectedComputePolicy !== null ? (
            <dl className="grid grid-cols-1 gap-1 text-meta sm:grid-cols-2">
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Provider Profile</dt>
                <dd className="text-text-primary">
                  {resolvedProfile?.name ?? selectedComputePolicy.provider_profile_name}
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Destination</dt>
                <dd className="text-text-primary">
                  {resolvedProfile?.local_cli_adapter !== null &&
                  resolvedProfile?.local_cli_adapter !== undefined
                    ? `local command (${resolvedProfile.local_cli_adapter})`
                    : (resolvedProfile?.endpoint ?? selectedComputePolicy.data_destination)}
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Credential reference</dt>
                <dd className="font-mono text-text-primary">
                  {resolvedProfile?.credential_reference ?? 'n/a'} (
                  {resolvedProfile?.credential_state ?? 'unknown'})
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Max output tokens / call</dt>
                <dd className="text-text-primary tabular-nums">
                  {selectedComputePolicy.max_output_tokens_per_call.toLocaleString('en-US')}
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt className="text-text-secondary">Budget</dt>
                <dd className="text-text-primary">
                  {selectedComputePolicy.budget_usd !== null
                    ? `$${selectedComputePolicy.budget_usd.toFixed(2)}`
                    : 'No budget limit'}
                </dd>
              </div>
            </dl>
          ) : null}
        </Section>

        <section
          aria-label="Start confirmation"
          className="rounded-lg border border-action-primary bg-surface p-4"
        >
          <h2 className="text-sm font-semibold text-text-primary">Confirm before starting</h2>
          <dl className="mt-2 flex flex-col gap-1 text-sm">
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Repository</dt>
              <dd className="text-text-primary">
                {selectedRepository?.display_name ?? '(not selected)'}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Target → Proposed</dt>
              <dd className="font-mono text-text-primary">
                {sourceSelection.target} → {sourceSelection.proposed}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Provider / Model</dt>
              <dd className="font-mono text-text-primary">
                {selectedComputePolicy
                  ? `${selectedComputePolicy.provider} / ${selectedComputePolicy.model}`
                  : '(not selected)'}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Data destination</dt>
              <dd className="text-text-primary">
                {selectedComputePolicy?.data_destination ?? '(not selected)'}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Known retention</dt>
              <dd className="text-text-primary">
                {selectedComputePolicy?.known_retention ?? '(not selected)'}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Policy versions</dt>
              <dd className="font-mono text-text-primary">
                review {selectedReviewPolicy?.version ?? '—'} · compute{' '}
                {selectedComputePolicy?.version ?? '—'}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-text-secondary">Budget / max output</dt>
              <dd className="text-text-primary">
                {selectedComputePolicy !== null
                  ? `${
                      selectedComputePolicy.budget_usd !== null
                        ? `$${selectedComputePolicy.budget_usd.toFixed(2)}`
                        : 'no budget limit'
                    } / ${selectedComputePolicy.max_output_tokens_per_call.toLocaleString('en-US')} tokens`
                  : '(not selected)'}
              </dd>
            </div>
          </dl>

          {submitError !== null ? (
            <p role="alert" className="mt-3 text-sm text-status-error">
              {submitError}
            </p>
          ) : null}

          <div className="mt-4 flex items-center gap-3">
            <Button type="submit" disabled={submitting || catalog.repositories.length === 0}>
              {submitting ? 'Starting…' : 'Start review'}
            </Button>
            <p className="text-meta text-text-secondary">
              Creates one attempt and opens its live detail. Repeated submission of this unchanged
              form returns the same attempt (idempotent).
            </p>
          </div>
        </section>
      </form>
    </main>
  )
}
