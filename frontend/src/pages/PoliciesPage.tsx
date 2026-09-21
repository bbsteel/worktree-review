import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { useAdminClient } from '../app/admin-client.ts'
import { useI18n } from '../i18n.tsx'
import { Badge } from '../components/ui/badge.tsx'
import { Button } from '../components/ui/button.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import { Tab, TabList, TabPanel, Tabs } from '../components/ui/tabs.tsx'
import type { ComputePolicyDto, ProviderProfileDto, ReviewPolicyDto } from '../data/api/dto.ts'
import { ApiError } from '../data/api/review-api-client.ts'
import { CopyValue } from '../features/review-detail/CopyValue.tsx'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'

function DefinitionRow({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-1.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <dt className="text-meta text-text-secondary">{term}</dt>
      <dd className="min-w-0 text-sm text-text-primary">{children}</dd>
    </div>
  )
}

function GlobList({ label, globs }: { label: string; globs: string[] }) {
  const { t } = useI18n()
  return (
    <DefinitionRow term={label}>
      {globs.length === 0 ? (
        <span className="text-text-secondary">{t('None')}</span>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {globs.map((glob) => (
            <li key={glob} className="break-all font-mono text-meta">
              {glob}
            </li>
          ))}
        </ul>
      )}
    </DefinitionRow>
  )
}

/**
 * Policies page (design 12.4): two semantically separated, read-only views.
 * Policies come from trusted locations outside the reviewed repository;
 * repository content is untrusted and cannot change gate rules.
 */
export function PoliciesPage() {
  const { t } = useI18n()
  const client = useAdminClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const section = searchParams.get('section') === 'compute' ? 'compute' : 'review'
  const [reviewPolicies, setReviewPolicies] = useState<ReviewPolicyDto[] | null>(null)
  const [computePolicies, setComputePolicies] = useState<ComputePolicyDto[] | null>(null)
  const [providerProfiles, setProviderProfiles] = useState<ProviderProfileDto[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadCounter, setReloadCounter] = useState(0)
  const [reviewPath, setReviewPath] = useState('')
  const [computePath, setComputePath] = useState('')
  const [computeProfileId, setComputeProfileId] = useState('')
  const [registering, setRegistering] = useState(false)
  const [registerError, setRegisterError] = useState<string | null>(null)
  const [registerNotice, setRegisterNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      client.listReviewPolicies(),
      client.listComputePolicies(),
      client.listProviderProfiles(),
    ])
      .then(([review, compute, profiles]) => {
        if (!cancelled) {
          setReviewPolicies(review)
          setComputePolicies(compute)
          setProviderProfiles(profiles)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(
            caught instanceof Error ? caught.message : t('Policies could not be loaded.'),
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [client, t, reloadCounter])

  async function registerReviewPolicy(event: FormEvent) {
    event.preventDefault()
    setRegistering(true)
    setRegisterError(null)
    setRegisterNotice(null)
    try {
      const registered = await client.registerReviewPolicy({ path: reviewPath.trim() })
      setReviewPath('')
      setRegisterNotice(t('Registered trusted Review Policy {name}.', { name: registered.name }))
      setReloadCounter((count) => count + 1)
    } catch (caught) {
      setRegisterError(
        caught instanceof ApiError
          ? `${caught.code}: ${caught.message}`
          : t('The policy could not be registered. Nothing was changed.'),
      )
    } finally {
      setRegistering(false)
    }
  }

  async function registerComputePolicy(event: FormEvent) {
    event.preventDefault()
    setRegistering(true)
    setRegisterError(null)
    setRegisterNotice(null)
    try {
      const registered = await client.registerComputePolicy({
        path: computePath.trim(),
        provider_profile_id: computeProfileId === '' ? null : computeProfileId,
      })
      setComputePath('')
      setRegisterNotice(t('Registered trusted Compute Policy {name}.', { name: registered.name }))
      setReloadCounter((count) => count + 1)
    } catch (caught) {
      setRegisterError(
        caught instanceof ApiError
          ? `${caught.code}: ${caught.message}`
          : t('The policy could not be registered. Nothing was changed.'),
      )
    } finally {
      setRegistering(false)
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6">
        <EmptyState
          title={t('Policies require the live review service')}
          description={`${t('The trusted policy registry could not be loaded: {error}.', { error: loadError })} ${t(
            'The prototype mock mode does not expose policy registration.',
          )}`}
        />
      </main>
    )
  }

  if (reviewPolicies === null || computePolicies === null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-8 w-48" label={t('Loading policies')} />
        <Skeleton className="mt-4 h-48 w-full" label={t('Loading policy registry')} />
      </main>
    )
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-6">
      <h1 className="text-xl font-semibold text-text-primary">{t('Policies')}</h1>
      <p className="mt-1 text-sm text-text-secondary">
        {t('Review Policy decides what is reviewed and how the gate is evaluated. Compute Policy decides the model, budget and call limits. Both come from trusted locations outside the reviewed repository — repository instructions, comments and documents are untrusted and cannot change gate rules.')}
      </p>

      <Tabs
        value={section}
        onValueChange={(next) => {
          const params = new URLSearchParams(searchParams)
          if (next === 'compute') {
            params.set('section', 'compute')
          } else {
            params.delete('section')
          }
          setSearchParams(params)
        }}
        className="mt-4"
      >
        <TabList aria-label={t('Policy kinds')}>
          <Tab value="review">{t('Review Policies')}</Tab>
          <Tab value="compute">{t('Compute Policies')}</Tab>
        </TabList>

        <TabPanel value="review">
          <form
            aria-label={t('Register trusted Review Policy')}
            className="mb-3 rounded-lg border border-border bg-surface p-4"
            onSubmit={(event) => void registerReviewPolicy(event)}
          >
            <h2 className="text-sm font-semibold text-text-primary">
              {t('Register trusted Review Policy')}
            </h2>
            <p className="mt-1 text-meta text-text-secondary">
              {t('The policy file must live on this server, outside every registered repository. The browser submits a path; it never uploads policy content.')}
            </p>
            <label className="mt-2 flex flex-col gap-1 text-meta text-text-secondary">
              {t('Trusted policy file path')}
              <input
                type="text"
                value={reviewPath}
                onChange={(event) => {
                  setReviewPath(event.target.value)
                }}
                className={`${FIELD_CLASS} font-mono`}
                placeholder="/home/you/trusted/review-policy.yaml"
                required
              />
            </label>
            <div className="mt-3 flex items-center gap-3">
              <Button variant="primary" size="sm" type="submit" disabled={registering || reviewPath.trim() === ''}>
                {registering ? t('Registering…') : t('Register Review Policy')}
              </Button>
              {registerNotice !== null ? (
                <span role="status" className="text-meta text-status-passed">
                  {registerNotice}
                </span>
              ) : null}
              {registerError !== null ? (
                <span role="alert" className="text-meta text-status-error">
                  {registerError}
                </span>
              ) : null}
            </div>
          </form>
          {reviewPolicies.length === 0 ? (
            <EmptyState
              title={t('No registered Review Policies')}
              description={t('A built-in default policy is used until trusted external policies are registered outside the reviewed repositories.')}
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {reviewPolicies.map((policy) => (
                <li
                  key={policy.policy_id}
                  className="rounded-lg border border-border bg-surface p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-text-primary">
                      {policy.name} {policy.version}
                    </h2>
                    {policy.builtin ? <Badge tone="neutral" label={t('Built-in')} /> : null}
                    <CopyValue value={policy.sha256} label={t('Review Policy SHA-256')} />
                  </div>
                  <dl className="mt-2">
                    <DefinitionRow term={t('Required dimensions')}>
                      <span className="font-mono text-meta">
                        {policy.required_dimensions.join(', ') || t('None')}
                      </span>
                    </DefinitionRow>
                    <DefinitionRow term={t('Blocking severities')}>
                      {policy.blocking_severities.join(', ') || t('None')}
                    </DefinitionRow>
                    <DefinitionRow term={t('Minimum blocking evidence band')}>
                      {policy.minimum_blocking_evidence_band}
                    </DefinitionRow>
                    <DefinitionRow term={t('Output language')}>{policy.output_language}</DefinitionRow>
                    <DefinitionRow term={t('Context rules')}>
                      {policy.context_rules.length === 0 ? (
                        <span className="text-text-secondary">{t('None')}</span>
                      ) : (
                        <ul className="flex flex-col gap-0.5 text-meta">
                          {policy.context_rules.map((rule) => (
                            <li key={rule}>{rule}</li>
                          ))}
                        </ul>
                      )}
                    </DefinitionRow>
                    <GlobList label={t('Mandatory globs')} globs={policy.mandatory_globs} />
                    <GlobList label={t('Optional globs')} globs={policy.optional_globs} />
                    <GlobList label={t('Excluded globs')} globs={policy.excluded_globs} />
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </TabPanel>

        <TabPanel value="compute">
          <form
            aria-label={t('Register trusted Compute Policy')}
            className="mb-3 rounded-lg border border-border bg-surface p-4"
            onSubmit={(event) => void registerComputePolicy(event)}
          >
            <h2 className="text-sm font-semibold text-text-primary">
              {t('Register trusted Compute Policy')}
            </h2>
            <p className="mt-1 text-meta text-text-secondary">
              {t('Bind the Compute Policy to a Provider Profile so reviews have a real compute connection. The binding is validated against the policy provider and, for local-cli, the command fingerprint.')}
            </p>
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Trusted policy file path')}
                <input
                  type="text"
                  value={computePath}
                  onChange={(event) => {
                    setComputePath(event.target.value)
                  }}
                  className={`${FIELD_CLASS} font-mono`}
                  placeholder="/home/you/trusted/compute-policy.yaml"
                  required
                />
              </label>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Bound Provider Profile')}
                <select
                  value={computeProfileId}
                  onChange={(event) => {
                    setComputeProfileId(event.target.value)
                  }}
                  className={FIELD_CLASS}
                >
                  <option value="">{t('Not bound (reviews cannot start)')}</option>
                  {providerProfiles.map((profile) => (
                    <option key={profile.profile_id} value={profile.profile_id}>
                      {profile.name} ({profile.provider})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <Button variant="primary" size="sm" type="submit" disabled={registering || computePath.trim() === ''}>
                {registering ? t('Registering…') : t('Register Compute Policy')}
              </Button>
              {registerNotice !== null ? (
                <span role="status" className="text-meta text-status-passed">
                  {registerNotice}
                </span>
              ) : null}
              {registerError !== null ? (
                <span role="alert" className="text-meta text-status-error">
                  {registerError}
                </span>
              ) : null}
            </div>
          </form>
          {computePolicies.length === 0 ? (
            <EmptyState
              title={t('No registered Compute Policies')}
              description={t('Register a trusted Compute Policy to control model, budget and data destination.')}
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {computePolicies.map((policy) => (
                <li
                  key={policy.policy_id}
                  className="rounded-lg border border-border bg-surface p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-text-primary">
                      {policy.name} {policy.version}
                    </h2>
                    <CopyValue value={policy.sha256} label={t('Compute Policy SHA-256')} />
                  </div>
                  <dl className="mt-2">
                    <DefinitionRow term={t('Provider / Model')}>
                      <span className="font-mono text-meta">
                        {policy.provider} / {policy.model}
                      </span>
                    </DefinitionRow>
                    <DefinitionRow term={t('Provider Profile reference')}>
                      {policy.provider_profile_id === '' ? (
                        <span className="text-status-error">
                          {t('Not bound — reviews using this policy cannot start')}
                        </span>
                      ) : (
                        policy.provider_profile_name
                      )}
                    </DefinitionRow>
                    <DefinitionRow term={t('Max output tokens per call')}>
                      <span className="tabular-nums">
                        {policy.max_output_tokens_per_call.toLocaleString('en-US')}
                      </span>
                    </DefinitionRow>
                    <DefinitionRow term={t('Review budget')}>
                      {policy.budget_usd !== null
                        ? `$${policy.budget_usd.toFixed(2)}`
                        : t('No budget limit')}
                    </DefinitionRow>
                    <DefinitionRow term={t('Pricing source')}>
                      {policy.pricing_source}
                      {policy.start_with_uncertain_pricing
                        ? ` — ${t('starts even when pricing is uncertain')}`
                        : ` — ${t('refuses to start when pricing is uncertain')}`}
                    </DefinitionRow>
                    <DefinitionRow term={t('Data destination')}>{policy.data_destination}</DefinitionRow>
                    <DefinitionRow term={t('Known retention')}>{policy.known_retention}</DefinitionRow>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </TabPanel>
      </Tabs>
    </main>
  )
}
