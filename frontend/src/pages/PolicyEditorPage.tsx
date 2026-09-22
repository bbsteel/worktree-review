import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useAdminClient } from '../app/admin-client.ts'
import { useI18n } from '../i18n.tsx'
import { Button } from '../components/ui/button.tsx'
import { EmptyState } from '../components/ui/empty-state.tsx'
import { Skeleton } from '../components/ui/skeleton.tsx'
import type { PolicyDocumentDto } from '../data/api/dto.ts'
import { ApiError } from '../data/api/review-api-client.ts'
import {
  computeFormFromDocument,
  parsePolicyDocument,
  patchPolicyTextFromComputeForm,
  patchPolicyTextFromReviewForm,
  reviewFormFromDocument,
  type ComputePolicyFormFields,
  type PolicyKind,
  type ReviewPolicyFormFields,
} from '../features/policies/policy-document-sync.ts'

const FIELD_CLASS =
  'min-h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'
const AREA_CLASS =
  'min-h-64 w-full rounded-md border border-border bg-surface px-2 py-2 font-mono text-meta text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'

export function PolicyEditorPage({ kind }: { kind: PolicyKind }) {
  const { t } = useI18n()
  const client = useAdminClient()
  const navigate = useNavigate()
  const { policyId = '' } = useParams()
  const [document, setDocument] = useState<PolicyDocumentDto | null>(null)
  const [yamlText, setYamlText] = useState('')
  const [reviewForm, setReviewForm] = useState<ReviewPolicyFormFields>({
    version: '',
    blockingSeverities: '',
  })
  const [computeForm, setComputeForm] = useState<ComputePolicyFormFields>({
    version: '',
    provider: '',
    model: '',
  })
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [conflictOnDisk, setConflictOnDisk] = useState(false)
  const [saving, setSaving] = useState(false)
  const [reloading, setReloading] = useState(false)

  const applyLoadedDocument = useCallback(
    (loaded: PolicyDocumentDto) => {
      setDocument(loaded)
      setYamlText(loaded.text)
      const parsed = parsePolicyDocument(loaded.text)
      if (kind === 'review') {
        setReviewForm(reviewFormFromDocument(parsed))
      } else {
        setComputeForm(computeFormFromDocument(parsed))
      }
      setSaveError(null)
      setConflictOnDisk(false)
    },
    [kind],
  )

  useEffect(() => {
    let cancelled = false
    const loader =
      kind === 'review'
        ? client.getReviewPolicyDocument(policyId)
        : client.getComputePolicyDocument(policyId)
    loader
      .then((loaded) => {
        if (cancelled) {
          return
        }
        applyLoadedDocument(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(
            caught instanceof Error ? caught.message : t('The policy document could not be loaded.'),
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [applyLoadedDocument, client, kind, policyId, t])

  const title = useMemo(
    () =>
      kind === 'review' ? t('Edit Review Policy') : t('Edit Compute Policy'),
    [kind, t],
  )

  function applyFormToYaml() {
    try {
      const next =
        kind === 'review'
          ? patchPolicyTextFromReviewForm(yamlText, reviewForm)
          : patchPolicyTextFromComputeForm(yamlText, computeForm)
      setYamlText(next)
      setSaveError(null)
      setConflictOnDisk(false)
    } catch (caught) {
      setSaveError(
        caught instanceof Error ? caught.message : t('The form could not be applied to YAML.'),
      )
    }
  }

  function syncFormFromYaml() {
    try {
      const parsed = parsePolicyDocument(yamlText)
      if (kind === 'review') {
        setReviewForm(reviewFormFromDocument(parsed))
      } else {
        setComputeForm(computeFormFromDocument(parsed))
      }
      setSaveError(null)
      setConflictOnDisk(false)
    } catch (caught) {
      setSaveError(
        caught instanceof Error ? caught.message : t('YAML could not be parsed into the form.'),
      )
    }
  }

  async function reloadFromDisk() {
    setReloading(true)
    setSaveError(null)
    try {
      const loaded =
        kind === 'review'
          ? await client.getReviewPolicyDocument(policyId)
          : await client.getComputePolicyDocument(policyId)
      applyLoadedDocument(loaded)
    } catch (caught) {
      setSaveError(
        caught instanceof ApiError
          ? `${caught.code}: ${caught.message}`
          : t('The policy document could not be loaded.'),
      )
    } finally {
      setReloading(false)
    }
  }

  async function save() {
    if (document === null) {
      return
    }
    setSaving(true)
    setSaveError(null)
    setConflictOnDisk(false)
    try {
      // Save submits the current YAML text only. Form edits require "Apply form to YAML" first.
      const saved =
        kind === 'review'
          ? await client.saveReviewPolicyDocument(policyId, {
              expected_content_sha256: document.content_sha256,
              text: yamlText,
            })
          : await client.saveComputePolicyDocument(policyId, {
              expected_content_sha256: document.content_sha256,
              text: yamlText,
            })
      applyLoadedDocument(saved)
    } catch (caught) {
      if (caught instanceof ApiError && caught.httpStatus === 409) {
        setConflictOnDisk(true)
        setSaveError(
          t('The policy file changed on disk. Reload the editor before saving again.'),
        )
      } else {
        setSaveError(
          caught instanceof ApiError
            ? `${caught.code}: ${caught.message}`
            : t('The policy could not be saved.'),
        )
      }
    } finally {
      setSaving(false)
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6">
        <EmptyState title={title} description={loadError} />
        <Link className="mt-4 inline-block text-sm text-text-secondary underline" to="/policies">
          {t('Back to Policies')}
        </Link>
      </main>
    )
  }

  if (document === null) {
    return (
      <main className="mx-auto w-full max-w-4xl px-6 py-6" aria-busy="true">
        <Skeleton className="h-8 w-56" label={t('Loading policy editor')} />
        <Skeleton className="mt-4 h-64 w-full" label={t('Loading policy document')} />
      </main>
    )
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">{title}</h1>
          <p className="mt-1 break-all font-mono text-meta text-text-secondary">{document.path}</p>
        </div>
        <Link className="text-sm text-text-secondary underline" to="/policies">
          {t('Back to Policies')}
        </Link>
      </div>

      <section className="mt-4 rounded-lg border border-border bg-surface p-4" aria-label={t('Form subset')}>
        <h2 className="text-sm font-semibold text-text-primary">{t('Form subset')}</h2>
        <p className="mt-1 text-meta text-text-secondary">
          {t('Only a few fields are edited here. Everything else stays in the YAML document.')}
        </p>
        {kind === 'review' ? (
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              {t('Version')}
              <input
                className={FIELD_CLASS}
                value={reviewForm.version}
                onChange={(event) => {
                  setReviewForm((current) => ({ ...current, version: event.target.value }))
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              {t('Blocking severities (comma-separated)')}
              <input
                className={FIELD_CLASS}
                value={reviewForm.blockingSeverities}
                onChange={(event) => {
                  setReviewForm((current) => ({
                    ...current,
                    blockingSeverities: event.target.value,
                  }))
                }}
              />
            </label>
          </div>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              {t('Version')}
              <input
                className={FIELD_CLASS}
                value={computeForm.version}
                onChange={(event) => {
                  setComputeForm((current) => ({ ...current, version: event.target.value }))
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              {t('Provider')}
              <input
                className={FIELD_CLASS}
                value={computeForm.provider}
                onChange={(event) => {
                  setComputeForm((current) => ({ ...current, provider: event.target.value }))
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-meta text-text-secondary">
              {t('Model')}
              <input
                className={FIELD_CLASS}
                value={computeForm.model}
                onChange={(event) => {
                  setComputeForm((current) => ({ ...current, model: event.target.value }))
                }}
              />
            </label>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="secondary" onClick={applyFormToYaml}>
            {t('Apply form to YAML')}
          </Button>
          <Button type="button" size="sm" variant="secondary" onClick={syncFormFromYaml}>
            {t('Sync form from YAML')}
          </Button>
        </div>
      </section>

      <section className="mt-4 rounded-lg border border-border bg-surface p-4" aria-label={t('Advanced YAML')}>
        <h2 className="text-sm font-semibold text-text-primary">{t('Advanced YAML')}</h2>
        <textarea
          className={`${AREA_CLASS} mt-2`}
          value={yamlText}
          spellCheck={false}
          onChange={(event) => {
            setYamlText(event.target.value)
          }}
        />
      </section>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button type="button" variant="primary" disabled={saving} onClick={() => void save()}>
          {saving ? t('Saving…') : t('Save policy')}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            navigate(kind === 'review' ? '/policies' : '/policies?section=compute')
          }}
        >
          {t('Cancel')}
        </Button>
        {conflictOnDisk ? (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={reloading}
            onClick={() => void reloadFromDisk()}
          >
            {reloading ? t('Reloading…') : t('Reload from disk')}
          </Button>
        ) : null}
        {saveError !== null ? (
          <span role="alert" className="text-meta text-status-error">
            {saveError}
          </span>
        ) : null}
      </div>
    </main>
  )
}
