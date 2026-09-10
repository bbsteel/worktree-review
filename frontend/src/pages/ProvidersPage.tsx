import { useEffect, useState } from 'react'
import { useAdminClient } from '../app/admin-client.ts'
import { useI18n } from '../i18n.tsx'
import { Badge } from '../components/ui/badge.tsx'
import { Button } from '../components/ui/button.tsx'
import { Dialog } from '../components/ui/dialog.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import type { ProviderProfileDto, ProviderTestResultDto } from '../data/api/dto.ts'
import { ApiError } from '../data/api/review-api-client.ts'
import {
  buildSaveProfileRequest,
  INITIAL_PROFILE_FORM,
  validateProfileForm,
  type ProfileKind,
  type ProviderProfileFormErrors,
  type ProviderProfileFormState,
} from '../features/providers/provider-profile-form.ts'
import { formatTimestamp } from '../features/review-detail/formatting.ts'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'
const ERROR_CLASS = 'mt-1 text-meta text-status-error'

const CREDENTIAL_STATE_LABEL: Record<ProviderProfileDto['credential_state'], string> = {
  configured: 'Configured',
  missing: 'Missing',
  invalid_reference: 'Invalid reference',
}

function healthLabel(profile: ProviderProfileDto, translate: (key: string) => string): string {
  const observedAt = formatTimestamp(profile.health.observed_at)
  switch (profile.health.status) {
    case 'healthy':
      return translate('Healthy at {timestamp}').replace('{timestamp}', observedAt)
    case 'last_call_failed':
      return translate('Last call failed at {timestamp}').replace('{timestamp}', observedAt)
    default:
      return translate('Not tested')
  }
}

/**
 * Provider Connection Profiles (design 12). Profiles hold connectivity only;
 * model, budget and retention live in Compute Policies. The page never
 * receives or displays credential values — only environment variable
 * references. Test Connection is an explicit action that may call the
 * provider or a local command.
 */
export function ProvidersPage() {
  const { t } = useI18n()
  const client = useAdminClient()
  const [profiles, setProfiles] = useState<ProviderProfileDto[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [form, setForm] = useState<ProviderProfileFormState>(INITIAL_PROFILE_FORM)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [errors, setErrors] = useState<ProviderProfileFormErrors>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [pendingTest, setPendingTest] = useState<ProviderProfileDto | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResultById, setTestResultById] = useState<Record<string, ProviderTestResultDto>>({})
  const [deleteErrorById, setDeleteErrorById] = useState<Record<string, string>>({})

  useEffect(() => {
    let cancelled = false
    client
      .listProviderProfiles()
      .then((list) => {
        if (!cancelled) {
          setProfiles(list)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(
            caught instanceof Error ? caught.message : t('Provider profiles could not be loaded.'),
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [client, t])

  function startEdit(profile: ProviderProfileDto) {
    setEditingId(profile.profile_id)
    setForm({
      profileKind: profile.local_cli_adapter !== null ? 'local-cli' : 'remote',
      name: profile.name,
      provider: profile.provider === 'local-cli' ? 'anthropic' : profile.provider,
      endpoint: profile.endpoint ?? '',
      credentialReference: profile.credential_reference ?? '',
      localCliAdapter: profile.local_cli_adapter ?? '',
      localCliCommandText: (profile.local_cli_command ?? []).join('\n'),
      adapterLabel: profile.adapter_label ?? '',
    })
    setErrors({})
    setSaveError(null)
  }

  async function save() {
    const nextErrors = validateProfileForm(form)
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const request = buildSaveProfileRequest(form)
      const saved =
        editingId === null
          ? await client.createProviderProfile(request)
          : await client.updateProviderProfile(editingId, request)
      setProfiles((current) => {
        const others = (current ?? []).filter(
          (profile) => profile.profile_id !== saved.profile_id,
        )
        return [...others, saved]
      })
      setForm(INITIAL_PROFILE_FORM)
      setEditingId(null)
    } catch (caught) {
      setSaveError(
        caught instanceof ApiError
          ? `${caught.code}: ${caught.message}`
          : t('The profile could not be saved. Nothing was changed.'),
      )
    } finally {
      setSaving(false)
    }
  }

  async function confirmTest() {
    if (pendingTest === null) {
      return
    }
    setTesting(true)
    try {
      const result = await client.testProviderProfile(pendingTest.profile_id)
      setTestResultById((current) => ({ ...current, [pendingTest.profile_id]: result }))
      setPendingTest(null)
    } catch (caught) {
      setTestResultById((current) => ({
        ...current,
        [pendingTest.profile_id]: {
          ok: false,
          detail:
            caught instanceof ApiError
              ? `${caught.code}: ${caught.message}`
              : t('The connection test failed before reaching the provider.'),
          tested_at: new Date().toISOString(),
        },
      }))
      setPendingTest(null)
    } finally {
      setTesting(false)
    }
  }

  async function removeProfile(profile: ProviderProfileDto) {
    try {
      await client.deleteProviderProfile(profile.profile_id)
      setProfiles((current) =>
        (current ?? []).filter((entry) => entry.profile_id !== profile.profile_id),
      )
      setDeleteErrorById((current) => {
        const next = { ...current }
        delete next[profile.profile_id]
        return next
      })
    } catch (caught) {
      setDeleteErrorById((current) => ({
        ...current,
        [profile.profile_id]:
          caught instanceof ApiError ? `${caught.code}: ${caught.message}` : t('Delete failed.'),
      }))
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6">
        <EmptyState
          title={t('Provider profiles require the live review service')}
          description={`${t('Profiles could not be loaded: {error}.', { error: loadError })} ${t(
            'The prototype mock mode does not manage provider connections.',
          )}`}
        />
      </main>
    )
  }

  if (profiles === null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-8 w-48" label={t('Loading provider profiles')} />
        <Skeleton className="mt-4 h-48 w-full" label={t('Loading profiles')} />
      </main>
    )
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-6">
      <h1 className="text-xl font-semibold text-text-primary">{t('Providers')}</h1>
      <p className="mt-1 text-sm text-text-secondary">
        {t('Connection profiles only. Model, budget, pricing, data destination and retention are configured in trusted Compute Policies — never duplicated here.')}
      </p>

      <section aria-label={t('Provider profiles')} className="mt-4">
        {profiles.length === 0 ? (
          <EmptyState
            title={t('No provider profiles')}
            description={t('Create a connection profile below. Credentials are environment variable references; secret values never reach the browser.')}
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {profiles.map((profile) => {
              const testResult = testResultById[profile.profile_id]
              const deleteError = deleteErrorById[profile.profile_id]
              return (
                <li
                  key={profile.profile_id}
                  className="rounded-lg border border-border bg-surface p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-text-primary">{profile.name}</h2>
                    {profile.is_default ? <Badge tone="neutral" label={t('Default connection')} /> : null}
                    <Badge
                      tone={
                        profile.credential_state === 'configured'
                          ? 'passed'
                          : profile.credential_state === 'missing'
                            ? 'warning'
                            : 'error'
                      }
                      label={t('Credential: {state}', { state: t(CREDENTIAL_STATE_LABEL[profile.credential_state]) })}
                    />
                    <span className="text-meta text-text-secondary">{healthLabel(profile, t)}</span>
                  </div>
                  <dl className="mt-2 grid grid-cols-1 gap-1 text-meta sm:grid-cols-2">
                    <div className="flex gap-1.5">
                      <dt className="text-text-secondary">{t('Provider')}</dt>
                      <dd className="font-mono text-text-primary">{profile.provider}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt className="text-text-secondary">
                        {profile.local_cli_adapter !== null ? t('Local adapter') : t('Endpoint')}
                      </dt>
                      <dd className="break-all font-mono text-text-primary">
                        {profile.local_cli_adapter !== null
                          ? `${profile.local_cli_adapter}${profile.adapter_label !== null ? ` (${profile.adapter_label})` : ''}`
                          : (profile.endpoint ?? t('provider default'))}
                      </dd>
                    </div>
                    {profile.local_cli_command !== null ? (
                      <div className="flex gap-1.5 sm:col-span-2">
                        <dt className="shrink-0 text-text-secondary">{t('Command argv (no shell)')}</dt>
                        <dd className="break-all font-mono text-text-primary">
                          {profile.local_cli_command.join(' ')}
                        </dd>
                      </div>
                    ) : null}
                    {profile.credential_reference !== null ? (
                      <div className="flex gap-1.5">
                        <dt className="text-text-secondary">{t('Credential reference')}</dt>
                        <dd className="font-mono text-text-primary">
                          {profile.credential_reference}
                        </dd>
                      </div>
                    ) : null}
                    {profile.last_used_at !== null ? (
                      <div className="flex gap-1.5">
                        <dt className="text-text-secondary">{t('Last used')}</dt>
                        <dd className="text-text-primary">
                          {formatTimestamp(profile.last_used_at)}
                        </dd>
                      </div>
                    ) : null}
                  </dl>

                  {testResult !== undefined ? (
                    <p
                      role="status"
                      className={`mt-2 text-meta ${testResult.ok ? 'text-status-passed' : 'text-status-error'}`}
                    >
                      {t('Test {result} at {timestamp} — {detail}', {
                        result: t(testResult.ok ? 'succeeded' : 'failed'),
                        timestamp: formatTimestamp(testResult.tested_at),
                        detail: testResult.detail,
                      })}
                    </p>
                  ) : null}
                  {deleteError !== undefined ? (
                    <p role="alert" className="mt-2 text-meta text-status-error">
                      {deleteError}
                    </p>
                  ) : null}

                  <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        startEdit(profile)
                      }}
                    >
                      {t('Edit')}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setPendingTest(profile)
                      }}
                    >
                      {t('Test connection')}
                    </Button>
                    {profile.referenced_by_history ? (
                      <span className="inline-flex min-h-9 items-center text-meta text-text-secondary">
                        {t('Referenced by history — historical snapshots are kept; delete unavailable.')}
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          void removeProfile(profile)
                        }}
                      >
                        {t('Delete')}
                      </Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section
        aria-label={editingId === null ? t('Create provider profile') : t('Edit provider profile')}
        className="mt-4 rounded-lg border border-border bg-surface p-4"
      >
        <h2 className="text-sm font-semibold text-text-primary">
          {editingId === null ? t('Create provider profile') : t('Edit provider profile')}
        </h2>
        <p className="mt-1 text-meta text-text-secondary">
          {t('Saving validates the schema, paths and executables only — it does not call the model.')}
        </p>

        <div role="radiogroup" aria-label={t('Profile kind')} className="mt-3 flex gap-4">
          {(['remote', 'local-cli'] as ProfileKind[]).map((kind) => (
            <label key={kind} className="flex min-h-9 items-center gap-2 text-sm text-text-primary">
              <input
                type="radio"
                name="profile-kind"
                value={kind}
                checked={form.profileKind === kind}
                onChange={() => {
                  setForm({ ...form, profileKind: kind })
                  setErrors({})
                }}
                className="h-4 w-4 accent-[var(--wr-action-primary)]"
              />
              {kind === 'remote' ? t('Remote provider') : t('Local CLI')}
            </label>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-meta text-text-secondary">
            {t('Name')}
            <input
              type="text"
              value={form.name}
              onChange={(event) => {
                setForm({ ...form, name: event.target.value })
              }}
              className={FIELD_CLASS}
              placeholder="openai-production"
            />
            {errors.name !== undefined ? <span className={ERROR_CLASS}>{errors.name}</span> : null}
          </label>

          {form.profileKind === 'remote' ? (
            <>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Provider')}
                <select
                  value={form.provider}
                  onChange={(event) => {
                    setForm({ ...form, provider: event.target.value })
                  }}
                  className={FIELD_CLASS}
                >
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Endpoint URL (optional)')}
                <input
                  type="text"
                  value={form.endpoint}
                  onChange={(event) => {
                    setForm({ ...form, endpoint: event.target.value })
                  }}
                  className={FIELD_CLASS}
                  placeholder="https://api.openai.com"
                />
                {errors.endpoint !== undefined ? (
                  <span className={ERROR_CLASS}>{errors.endpoint}</span>
                ) : null}
              </label>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Credential reference (environment variable name, never the value)')}
                <input
                  type="text"
                  value={form.credentialReference}
                  onChange={(event) => {
                    setForm({ ...form, credentialReference: event.target.value })
                  }}
                  className={FIELD_CLASS}
                  placeholder="${OPENAI_API_KEY}"
                />
                {errors.credentialReference !== undefined ? (
                  <span className={ERROR_CLASS}>{errors.credentialReference}</span>
                ) : null}
              </label>
            </>
          ) : (
            <>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Adapter')}
                <input
                  type="text"
                  value={form.localCliAdapter}
                  onChange={(event) => {
                    setForm({ ...form, localCliAdapter: event.target.value })
                  }}
                  className={FIELD_CLASS}
                  placeholder="codex-cli"
                />
                {errors.localCliAdapter !== undefined ? (
                  <span className={ERROR_CLASS}>{errors.localCliAdapter}</span>
                ) : null}
              </label>
              <label className="flex flex-col gap-1 text-meta text-text-secondary">
                {t('Adapter label (optional)')}
                <input
                  type="text"
                  value={form.adapterLabel}
                  onChange={(event) => {
                    setForm({ ...form, adapterLabel: event.target.value })
                  }}
                  className={FIELD_CLASS}
                />
              </label>
              <label className="flex flex-col gap-1 text-meta text-text-secondary sm:col-span-2">
                {t('Command argv (one argument per line; executed without a shell)')}
                <textarea
                  value={form.localCliCommandText}
                  onChange={(event) => {
                    setForm({ ...form, localCliCommandText: event.target.value })
                  }}
                  className={`${FIELD_CLASS} min-h-20 font-mono`}
                  placeholder={'codex\nexec\n--json'}
                />
                {errors.localCliCommandText !== undefined ? (
                  <span className={ERROR_CLASS}>{errors.localCliCommandText}</span>
                ) : null}
              </label>
              <p className="text-meta text-text-secondary sm:col-span-2">
                {t("Local execution does not guarantee that inference, network access or retention stay on this machine — check the adapter's own disclosures.")}
              </p>
            </>
          )}
        </div>

        {saveError !== undefined && saveError !== null ? (
          <p role="alert" className="mt-2 text-sm text-status-error">
            {saveError}
          </p>
        ) : null}

        <div className="mt-3 flex gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={saving}
            onClick={() => {
              void save()
            }}
          >
            {saving ? t('Saving…') : editingId === null ? t('Create profile') : t('Save changes')}
          </Button>
          {editingId !== null ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditingId(null)
                setForm(INITIAL_PROFILE_FORM)
                setErrors({})
              }}
            >
              {t('Cancel edit')}
            </Button>
          ) : null}
        </div>
      </section>

      <Dialog
        open={pendingTest !== null}
        title={t('Test provider connection')}
        description={t('This is an explicit action: it makes one real call to the provider endpoint or local command.')}
        onClose={() => {
          if (!testing) {
            setPendingTest(null)
          }
        }}
      >
        {pendingTest !== null ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-text-primary">
              {t('Test')} <span className="font-mono">{pendingTest.name}</span> {t('now?')}
            </p>
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={testing}
                onClick={() => {
                  setPendingTest(null)
                }}
              >
                {t('Cancel')}
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={testing}
                onClick={() => {
                  void confirmTest()
                }}
              >
                {testing ? t('Testing…') : t('Run test')}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </main>
  )
}
