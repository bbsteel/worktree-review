import type { ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { CopyValue } from './CopyValue.tsx'

/**
 * Policies tab (design 13.9): the actual policy snapshots this attempt used,
 * not the current profile state. The trust boundary note is fixed copy.
 */
export function PoliciesTab({ run }: { run: ReviewRunView }) {
  const { t } = useI18n()
  const policies = run.policies

  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-secondary">
        <span className="font-semibold text-text-primary">{t('Review Policy')}</span> {t('decides what is reviewed and how the gate is evaluated;')}{' '}
        <span className="font-semibold text-text-primary">{t('Compute Policy')}</span> {t('decides the model, budget and call limits. Policies come from trusted locations outside the reviewed repository — repository content, comments and instructions are untrusted and cannot change gate rules.')}
      </p>

      <section aria-label={t('Review Policy snapshot')} className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">{t('Review Policy snapshot')}</h2>
        <dl className="mt-2 flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">{t('Name / Version')}</dt>
            <dd className="font-mono text-text-primary">
              {policies.reviewPolicyName} {policies.reviewPolicyVersion}
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">SHA-256</dt>
            <dd>
              <CopyValue value={policies.reviewPolicySha256} label={t('Review Policy SHA-256')} />
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label={t('Compute Policy snapshot')} className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">{t('Compute Policy snapshot')}</h2>
        <dl className="mt-2 flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">{t('Name / Version')}</dt>
            <dd className="font-mono text-text-primary">
              {policies.computePolicyName} {policies.computePolicyVersion}
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">SHA-256</dt>
            <dd>
              <CopyValue value={policies.computePolicySha256} label={t('Compute Policy SHA-256')} />
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">{t('Provider / Model')}</dt>
            <dd className="font-mono text-text-primary">
              {run.summary.provider} / {run.summary.model}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">{t('Data destination')}</dt>
            <dd className="text-text-primary">{policies.dataDestination}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">{t('Known retention')}</dt>
            <dd className="text-text-primary">{policies.retentionDisclosure}</dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">{t('Provider configuration fingerprint')}</dt>
            <dd>
              {policies.providerConfigurationFingerprint !== null ? (
                <CopyValue
                  value={policies.providerConfigurationFingerprint}
                  label={t('Provider configuration fingerprint')}
                  truncate={false}
                />
              ) : (
                <span className="text-text-secondary">{t('Not reported')}</span>
              )}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  )
}
