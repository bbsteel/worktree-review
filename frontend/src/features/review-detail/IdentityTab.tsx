import type { ReactNode } from 'react'
import type { ReviewRunView } from '../../domain/review.ts'
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
  const identity = run.identity
  const identityAvailable = identity.reviewIdentity !== null

  return (
    <div className="flex flex-col gap-4">
      {!identityAvailable ? (
        <p role="alert" className="rounded-lg border border-status-error bg-surface p-4 text-sm text-status-error">
          {identity.identityUnavailableReason ??
            'Review identity unavailable — merge candidate was not constructed.'}
        </p>
      ) : null}

      <section
        aria-label="Identity relationship"
        className="rounded-lg border border-border bg-surface p-4"
      >
        <h2 className="text-sm font-semibold text-text-primary">How these identities relate</h2>
        <ul className="mt-2 flex flex-col gap-1 text-sm text-text-secondary">
          <li>
            <span className="text-text-primary">Review Request Key</span> — what the system was
            asked to review.
          </li>
          <li className="pl-4">
            └─ once the merge is constructed, the{' '}
            <span className="text-text-primary">Review Identity</span> defines what the conclusion
            applies to.
          </li>
          <li>
            <span className="text-text-primary">Attempt</span> — which execution produced this
            result.
          </li>
          {run.source.kind === 'github-pull-request' ? (
            <li className="pl-4">
              └─ the authoritative, current attempt governs the{' '}
              <span className="text-text-primary">Standing Decision</span>.
            </li>
          ) : (
            <li className="pl-4">└─ local one-shot results never change a standing decision.</li>
          )}
        </ul>
      </section>

      <section aria-label="Identity fields" className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-1 text-sm font-semibold text-text-primary">Identity fields</h2>
        <dl>
          <IdentityRow term="Review Request Key" description="What the system was asked to review">
            <span className="break-all font-mono text-meta">{identity.reviewRequestKey}</span>
          </IdentityRow>
          <IdentityRow term="Source Repository">
            <span className="break-all">{identity.sourceRepository}</span>
          </IdentityRow>
          <IdentityRow term="Target Ref">
            <span className="font-mono text-meta">{identity.targetRef}</span>
          </IdentityRow>
          <IdentityRow term="Target Head OID">
            {identity.targetHeadOid !== null ? (
              <CopyValue value={identity.targetHeadOid} label="Target Head OID" />
            ) : (
              'Not resolved'
            )}
          </IdentityRow>
          <IdentityRow term="Proposed Source">
            <span className="font-mono text-meta">{identity.proposedSource}</span>
          </IdentityRow>
          <IdentityRow term="Proposed Head OID">
            {identity.proposedHeadOid !== null ? (
              <CopyValue value={identity.proposedHeadOid} label="Proposed Head OID" />
            ) : (
              'Not resolved'
            )}
          </IdentityRow>
          <IdentityRow term="Merge Tree OID" description="Exact merge result that was reviewed">
            {identity.mergeTreeOid !== null ? (
              <CopyValue value={identity.mergeTreeOid} label="Merge Tree OID" />
            ) : (
              'Not constructed'
            )}
          </IdentityRow>
          <IdentityRow term="Review Identity" description="What the gate conclusion applies to">
            {identity.reviewIdentity !== null ? (
              <CopyValue value={identity.reviewIdentity} label="Review Identity" />
            ) : (
              'Unavailable — see the notice above'
            )}
          </IdentityRow>
          <IdentityRow term="Attempt ID" description="Which execution produced this result">
            <CopyValue value={run.attemptId} label="Attempt ID" truncate={false} />
          </IdentityRow>
          <IdentityRow term="Review Policy">
            <span className="font-mono text-meta">
              {run.policies.reviewPolicyName} {run.policies.reviewPolicyVersion}
            </span>{' '}
            <CopyValue value={run.policies.reviewPolicySha256} label="Review Policy SHA-256" />
          </IdentityRow>
          <IdentityRow term="Compute Policy">
            <span className="font-mono text-meta">
              {run.policies.computePolicyName} {run.policies.computePolicyVersion}
            </span>{' '}
            <CopyValue value={run.policies.computePolicySha256} label="Compute Policy SHA-256" />
          </IdentityRow>
        </dl>
      </section>
    </div>
  )
}
