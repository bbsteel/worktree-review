import { RotateCcw } from 'lucide-react'
import { Button } from '../../components/ui/button.tsx'
import { Dialog } from '../../components/ui/dialog.tsx'
import type { ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'

interface RetryConfirmDialogProps {
  open: boolean
  run: ReviewRunView
  onClose: () => void
  onConfirm: () => void
}

/**
 * Retry confirmation (B-014). The copy is source-adaptive and frozen:
 * a GitHub authoritative retry must state that the standing decision is
 * revoked until the new attempt completes; a local retry only creates a new
 * attempt and must never mention a standing decision.
 */
export function RetryConfirmDialog({ open, run, onClose, onConfirm }: RetryConfirmDialogProps) {
  const isGitHub = run.source.kind === 'github-pull-request'
  const { t } = useI18n()

  return (
    <Dialog
      open={open}
      title={t('Retry this review?')}
      description={
        isGitHub
          ? t(
              'Retry creates a new authoritative attempt and temporarily revokes the current standing decision until the new review completes.',
            )
          : t('Retry creates a new local attempt. The current result stays as immutable history.')
      }
      onClose={onClose}
    >
      <div className="flex flex-col gap-3 text-sm text-text-secondary">
        {isGitHub ? (
          <>
            <p>
              {t('The new attempt supersedes')} <span className="font-mono">{run.attemptId}</span>. {t(
                'The old attempt is kept as superseded history and is never overwritten.',
              )}
            </p>
            <p>
              {t('While the new review runs, the previous gate result no longer governs this pull request.')}
            </p>
          </>
        ) : (
          <p>
            {t('A new attempt re-runs the same inputs under a new attempt ID. Nothing about the current result is modified.')}
          </p>
        )}
        <p className="text-meta text-text-secondary">
          {t('Prototype: confirming simulates the interaction locally — no request is sent.')}
        </p>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('Cancel')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              onConfirm()
              onClose()
            }}
          >
            <RotateCcw aria-hidden="true" className="h-4 w-4" />
            {t('Create new attempt')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
