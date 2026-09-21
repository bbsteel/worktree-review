import { ShieldAlert } from 'lucide-react'
import { useId, useState } from 'react'
import { useDataSource } from '../../app/data-source.ts'
import { Button } from '../../components/ui/button.tsx'
import { Dialog } from '../../components/ui/dialog.tsx'
import { ApiError } from '../../data/api/review-api-client.ts'
import type { BypassSubmissionView } from '../../domain/audit.ts'
import type { ReviewFindingView, ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'

interface BypassRiskDialogProps {
  open: boolean
  run: ReviewRunView
  /** The single blocking finding whose risk is being accepted (P3: never whole-gate). */
  finding: ReviewFindingView
  onClose: () => void
  /** Called after the server persisted the bypass; the parent refetches the run. */
  onSubmitted: (result: BypassSubmissionView) => void
  /**
   * Called on a 409: the candidate, authority, or policy moved under the
   * dialog. The parent must close the stale confirmation context and refetch
   * the authoritative state (P3 §9.1).
   */
  onConflict: () => void
}

type SubmitError =
  | { kind: 'conflict' }
  | { kind: 'unavailable' }
  | { kind: 'auth' }
  | { kind: 'invalid-reason' }
  | { kind: 'other'; message: string }

function classifySubmitError(error: unknown): SubmitError {
  if (error instanceof ApiError) {
    if (error.httpStatus === 409) return { kind: 'conflict' }
    if (error.httpStatus === 503) return { kind: 'unavailable' }
    if (error.httpStatus === 401) return { kind: 'auth' }
    if (error.code === 'bypass_reason_invalid') return { kind: 'invalid-reason' }
    return { kind: 'other', message: error.message }
  }
  return {
    kind: 'other',
    message: error instanceof Error ? error.message : 'Unknown error',
  }
}

/**
 * Per-finding risk acceptance (B-300 / P3 §9.1). The frozen copy always frames
 * bypass as accepting risk — never as resolving the finding — and requires a
 * non-empty reason before the confirm control is enabled. Submission goes to
 * the real API; a 409 closes the stale context and asks for a refetch, a 503
 * keeps the typed reason for retry, and a 401 points at re-authentication.
 */
export function BypassRiskDialog({
  open,
  run,
  finding,
  onClose,
  onSubmitted,
  onConflict,
}: BypassRiskDialogProps) {
  const { t } = useI18n()
  const { source } = useDataSource()
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<SubmitError | null>(null)

  function close() {
    // Never drop an in-flight request's observable outcome: closing is only
    // possible while idle.
    if (submitting) return
    setReason('')
    setSubmitError(null)
    onClose()
  }

  async function submit() {
    if (source.bypassFinding === undefined) {
      setSubmitError({ kind: 'unavailable' })
      return
    }
    setSubmitting(true)
    setSubmitError(null)
    try {
      const result = await source.bypassFinding(run.attemptId, finding.fingerprint, trimmedReason)
      setSubmitting(false)
      setReason('')
      onSubmitted(result)
      onClose()
    } catch (error) {
      setSubmitting(false)
      const classified = classifySubmitError(error)
      if (classified.kind === 'conflict') {
        // The confirmation context is stale: close it and let the parent
        // refetch the authoritative state instead of lingering (P3 §9.1).
        onConflict()
        return
      }
      setSubmitError(classified)
    }
  }

  const remainingBlocking = run.gate.remainingBlockingFingerprints ?? []
  const trimmedReason = reason.trim()

  return (
    <Dialog
      open={open}
      title={t('Accept the risk of this finding?')}
      description={t('Bypass means accepting the risk. It does not mean the finding was resolved.')}
      onClose={close}
    >
      <div className="flex flex-col gap-3 text-sm text-text-secondary">
        <div className="rounded-md border border-status-warning/40 bg-surface-subtle p-3">
          <p className="font-medium text-text-primary">{finding.problemStatement}</p>
          <p className="mt-1 text-meta">
            <span className="font-mono">{finding.fingerprint}</span> · {t(finding.severity)} ·{' '}
            {t(finding.dimensionId)}
          </p>
          {remainingBlocking.length > 1 ? (
            <p className="mt-2 text-meta">
              {t('{count} other blocking findings remain after this acceptance.', {
                count: remainingBlocking.length - 1,
              })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={reasonId} className="font-medium text-text-primary">
            {t('Reason (required)')}
          </label>
          <textarea
            id={reasonId}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            disabled={submitting}
            placeholder={t('Why is accepting this risk justified?')}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        </div>
        {submitError !== null ? (
          submitError.kind === 'auth' ? (
            <p role="alert" className="text-sm text-status-blocked">
              {t('Your GitHub session expired.')}{' '}
              <a
                href="/api/v1/auth/github/start"
                className="text-action-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
              >
                {t('Sign in with GitHub')}
              </a>
            </p>
          ) : (
            <p role="alert" className="text-sm text-status-blocked">
              {submitError.kind === 'unavailable'
                ? t('GitHub or the audit store could not decide. Your reason is preserved — retry when the service recovers.')
                : submitError.kind === 'invalid-reason'
                  ? t('The reason is empty, too long, or contains credential-shaped content.')
                  : submitError.kind === 'other'
                    ? t('The bypass request failed: {message}', { message: submitError.message })
                    : t('The candidate, authority, or policy changed. The risk was not accepted — review the refreshed state.')}
            </p>
          )
        ) : null}
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={close} disabled={submitting}>
            {t('Cancel')}
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={trimmedReason.length === 0 || submitting}
            aria-describedby={trimmedReason.length === 0 ? `${reasonId}-required` : undefined}
            onClick={() => void submit()}
          >
            <ShieldAlert aria-hidden="true" className="h-4 w-4" />
            {submitting ? t('Submitting…') : t('Accept risk')}
          </Button>
        </div>
        {trimmedReason.length === 0 ? (
          <p id={`${reasonId}-required`} className="text-right text-meta text-text-secondary">
            {t('Enter a reason to enable this action.')}
          </p>
        ) : null}
      </div>
    </Dialog>
  )
}
