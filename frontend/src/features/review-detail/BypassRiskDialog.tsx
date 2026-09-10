import { ShieldAlert } from 'lucide-react'
import { useId, useState } from 'react'
import { Button } from '../../components/ui/button.tsx'
import { Dialog } from '../../components/ui/dialog.tsx'
import type { ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'

interface BypassRiskDialogProps {
  open: boolean
  run: ReviewRunView
  onClose: () => void
  onConfirm: (reason: string) => void
}

/**
 * Bypass risk confirmation (B-014). The frozen copy always frames bypass as
 * accepting risk — never as resolving the findings — and requires a non-empty
 * reason before the confirm control is enabled. Only reachable when the
 * capability view marks bypass as enabled; Error, superseded and
 * unauthorized states never expose it.
 */
export function BypassRiskDialog({ open, run, onClose, onConfirm }: BypassRiskDialogProps) {
  const { t } = useI18n()
  const reasonId = useId()
  const [reason, setReason] = useState('')

  function close() {
    setReason('')
    onClose()
  }

  const blockingFindings = run.findings.filter((finding) => finding.blocking)
  const trimmedReason = reason.trim()

  return (
    <Dialog
      open={open}
      title={t('Accept the risk and bypass the gate?')}
      description={t('Bypass means accepting the risk. It does not mean the finding was resolved.')}
      onClose={close}
    >
      <div className="flex flex-col gap-3 text-sm text-text-secondary">
        <div className="rounded-md border border-status-warning/40 bg-surface-subtle p-3">
          <p className="font-medium text-text-primary">
            {blockingFindings.length} {t('blocking')} {t(blockingFindings.length === 1 ? 'finding' : 'findings')}{' '}
            {t('accepted as risk')}
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {blockingFindings.map((finding) => (
              <li key={finding.fingerprint} className="text-meta">
                <span className="font-mono">{finding.fingerprint}</span> — {finding.problemStatement}
              </li>
            ))}
          </ul>
        </div>
        <p>
          {t('If confirmed, the gate becomes')} <strong>{t('Passed with Bypass')}</strong>{' '}
          {t('and this decision records your reason. The findings stay open and remain visible as accepted risk.')}
        </p>
        <div className="flex flex-col gap-1">
          <label htmlFor={reasonId} className="font-medium text-text-primary">
            {t('Reason (required)')}
          </label>
          <textarea
            id={reasonId}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            placeholder={t('Why is accepting this risk justified?')}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        </div>
        <p className="text-meta text-text-secondary">
          {t('Prototype: confirming simulates the interaction locally — no request is sent.')}
        </p>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={close}>
            {t('Cancel')}
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={trimmedReason.length === 0}
            aria-describedby={trimmedReason.length === 0 ? `${reasonId}-required` : undefined}
            onClick={() => {
              onConfirm(trimmedReason)
              close()
            }}
          >
            <ShieldAlert aria-hidden="true" className="h-4 w-4" />
            {t('Accept risk and bypass')}
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
