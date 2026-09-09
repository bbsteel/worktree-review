import type { ReviewRunView } from '../../domain/review.ts'
import { CopyValue } from './CopyValue.tsx'

/**
 * Policies tab (design 13.9): the actual policy snapshots this attempt used,
 * not the current profile state. The trust boundary note is fixed copy.
 */
export function PoliciesTab({ run }: { run: ReviewRunView }) {
  const policies = run.policies

  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-secondary">
        <span className="font-semibold text-text-primary">Review Policy</span> decides what is
        reviewed and how the gate is evaluated;{' '}
        <span className="font-semibold text-text-primary">Compute Policy</span> decides the model,
        budget and call limits. Policies come from trusted locations outside the reviewed
        repository — repository content, comments and instructions are untrusted and cannot change
        gate rules.
      </p>

      <section aria-label="Review Policy snapshot" className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">Review Policy snapshot</h2>
        <dl className="mt-2 flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">Name / Version</dt>
            <dd className="font-mono text-text-primary">
              {policies.reviewPolicyName} {policies.reviewPolicyVersion}
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">SHA-256</dt>
            <dd>
              <CopyValue value={policies.reviewPolicySha256} label="Review Policy SHA-256" />
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label="Compute Policy snapshot" className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-primary">Compute Policy snapshot</h2>
        <dl className="mt-2 flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">Name / Version</dt>
            <dd className="font-mono text-text-primary">
              {policies.computePolicyName} {policies.computePolicyVersion}
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">SHA-256</dt>
            <dd>
              <CopyValue value={policies.computePolicySha256} label="Compute Policy SHA-256" />
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">Provider / Model</dt>
            <dd className="font-mono text-text-primary">
              {run.summary.provider} / {run.summary.model}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">Data destination</dt>
            <dd className="text-text-primary">{policies.dataDestination}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-text-secondary">Known retention</dt>
            <dd className="text-text-primary">{policies.retentionDisclosure}</dd>
          </div>
          <div className="flex flex-wrap items-center gap-x-2">
            <dt className="text-text-secondary">Provider configuration fingerprint</dt>
            <dd>
              {policies.providerConfigurationFingerprint !== null ? (
                <CopyValue
                  value={policies.providerConfigurationFingerprint}
                  label="Provider configuration fingerprint"
                  truncate={false}
                />
              ) : (
                <span className="text-text-secondary">Not reported</span>
              )}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  )
}
