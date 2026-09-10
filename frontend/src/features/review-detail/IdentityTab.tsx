import type { ReactNode } from 'react'
import type { ReviewRunView } from '../../domain/review.ts'
import { useI18n } from '../../i18n.tsx'
import { CopyValue } from './CopyValue.tsx'

function IdentityRow({
  term,
  description,
  children,
}: {
  term: string
  description?: string
  children: ReactNode
}) {
  return (
    <div className="grid grid-cols-1 gap-1 border-b border-border py-2 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <dt className="text-sm text-text-secondary">
        {term}
        {description !== undefined ? (
          <span className="block text-meta text-text-secondary">{description}</span>
        ) : null}
      </dt>
      <dd className="min-w-0 text-sm text-text-primary">{children}</dd>
    </div>
  )
}

/**
 * Identity & Provenance tab (design 13.8). When the merge candidate was not
 * constructed the tab shows the fixed unavailable message and never renders
 * placeholder OIDs or a fabricated Review Identity.
 */
export function IdentityTab({ run }: { run: ReviewRunView }) {
  const { t } = useI18n()
  const identity = run.identity
  const identityAvailable = identity.reviewIdentity !== null

  return (
    <div className="flex flex-col gap-4">
      {!identityAvailable ? (
        <p role="alert" className="rounded-lg border border-status-error bg-surface p-4 text-sm text-status-error">
          {identity.identityUnavailableReason ??
            t('Review identity unavailable — merge candidate was not constructed.')}
        </p>
      ) : null}

      <section
        aria-label={t('Identity relationship')}
        className="rounded-lg border border-border bg-surface p-4"
      >
        <h2 className="text-sm font-semibold text-text-primary">{t('How these identities relate')}</h2>
        <ul className="mt-2 flex flex-col gap-1 text-sm text-text-secondary">
          <li>
            <span className="text-text-primary">{t('Review Request Key')}</span> — {t('what the system was asked to review.')}
          </li>
          <li className="pl-4">
              └─ {t('once the merge is constructed, the')} <span className="text-text-primary">{t('Review Identity')}</span>{' '}
              {t('defines what the conclusion applies to.')}
          </li>
          <li>
            <span className="text-text-primary">{t('Attempt')}</span> — {t('which execution produced this result.')}
          </li>
          {run.source.kind === 'github-pull-request' ? (
            <li className="pl-4">
              └─ {t('the authoritative, current attempt governs the')} <span className="text-text-primary">{t('Standing Decision')}</span>.
            </li>
          ) : (
            <li className="pl-4">└─ {t('local one-shot results never change a standing decision.')}</li>
          )}
        </ul>
      </section>

      <section aria-label={t('Identity fields')} className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-1 text-sm font-semibold text-text-primary">{t('Identity fields')}</h2>
        <dl>
          <IdentityRow term={t('Review Request Key')} description={t('What the system was asked to review')}>
            <span className="break-all font-mono text-meta">{identity.reviewRequestKey}</span>
          </IdentityRow>
          <IdentityRow term={t('Source Repository')}>
            <span className="break-all">{identity.sourceRepository}</span>
          </IdentityRow>
          <IdentityRow term={t('Target Ref')}>
            <span className="font-mono text-meta">{identity.targetRef}</span>
          </IdentityRow>
          <IdentityRow term={t('Target Head OID')}>
            {identity.targetHeadOid !== null ? (
              <CopyValue value={identity.targetHeadOid} label={t('Target Head OID')} />
            ) : (
              t('Not resolved')
            )}
          </IdentityRow>
          <IdentityRow term={t('Proposed Source')}>
            <span className="font-mono text-meta">{identity.proposedSource}</span>
          </IdentityRow>
          <IdentityRow term={t('Proposed Head OID')}>
            {identity.proposedHeadOid !== null ? (
              <CopyValue value={identity.proposedHeadOid} label={t('Proposed Head OID')} />
            ) : (
              t('Not resolved')
            )}
          </IdentityRow>
          <IdentityRow term={t('Merge Tree OID')} description={t('Exact merge result that was reviewed')}>
            {identity.mergeTreeOid !== null ? (
              <CopyValue value={identity.mergeTreeOid} label={t('Merge Tree OID')} />
            ) : (
              t('Not constructed')
            )}
          </IdentityRow>
          <IdentityRow term={t('Review Identity')} description={t('What the gate conclusion applies to')}>
            {identity.reviewIdentity !== null ? (
              <CopyValue value={identity.reviewIdentity} label={t('Review Identity')} />
            ) : (
              t('Unavailable — see the notice above')
            )}
          </IdentityRow>
          <IdentityRow term={t('Attempt ID')} description={t('Which execution produced this result')}>
            <CopyValue value={run.attemptId} label={t('Attempt ID')} truncate={false} />
          </IdentityRow>
          <IdentityRow term={t('Review Policy')}>
            <span className="font-mono text-meta">
              {run.policies.reviewPolicyName} {run.policies.reviewPolicyVersion}
            </span>{' '}
            <CopyValue value={run.policies.reviewPolicySha256} label={t('Review Policy SHA-256')} />
          </IdentityRow>
          <IdentityRow term={t('Compute Policy')}>
            <span className="font-mono text-meta">
              {run.policies.computePolicyName} {run.policies.computePolicyVersion}
            </span>{' '}
            <CopyValue value={run.policies.computePolicySha256} label={t('Compute Policy SHA-256')} />
          </IdentityRow>
        </dl>
      </section>
    </div>
  )
}
