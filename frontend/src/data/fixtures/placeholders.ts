import type {
  AvailableReviewActionsView,
  CoverageView,
  GateDecisionView,
  PolicySnapshotView,
  ProviderHealthView,
  ReviewAttemptView,
  ReviewIdentityView,
  ReviewRunView,
  ReviewSourceView,
  ReviewSummaryView,
  ReviewUsageView,
} from '../../domain/review.ts'

const unavailableActions: AvailableReviewActionsView = {
  retry: {
    visible: true,
    enabled: false,
    disabledReason: 'Prototype foundation placeholder — Retry is not wired yet.',
  },
  bypass: {
    visible: true,
    enabled: false,
    disabledReason: 'Prototype foundation placeholder — Bypass is not wired yet.',
  },
  openCheck: {
    visible: false,
    enabled: false,
    disabledReason: 'Open Check is not available in the prototype foundation.',
  },
  openSessionInsight: {
    visible: true,
    enabled: false,
    disabledReason: 'Session Insight is not connected in the prototype foundation.',
  },
}

const emptyCoverage: CoverageView = {
  requiredCoverage: 'incomplete',
  reviewedCount: 0,
  excludedCount: 0,
  missingCount: 0,
  files: [],
}

const emptyUsage: ReviewUsageView = {
  estimatedCostUsd: null,
  actualCostUsd: null,
  costUnknown: true,
  unknownCostRecordCount: 0,
  inputTokens: null,
  outputTokens: null,
  calls: [],
}

const placeholderPolicies: PolicySnapshotView = {
  reviewPolicyName: 'placeholder-review-policy',
  reviewPolicyVersion: '0.0.0',
  reviewPolicySha256: '0'.repeat(64),
  computePolicyName: 'placeholder-compute-policy',
  computePolicyVersion: '0.0.0',
  computePolicySha256: '0'.repeat(64),
  dataDestination: 'not-reported',
  retentionDisclosure: 'not-reported',
  providerConfigurationFingerprint: null,
}

const placeholderProviderHealth: ProviderHealthView = {
  profileName: 'placeholder',
  status: 'not_tested',
  observedAt: null,
}

function sourceForCase(kind: ReviewRunView['source']['kind']): ReviewSourceView {
  if (kind === 'github-pull-request') {
    return {
      kind: 'github-pull-request',
      repositoryFullName: 'acme/payment-service',
      pullRequestNumber: 184,
      pullRequestTitle: 'Harden webhook authorization',
      authorLogin: 'placeholder',
      proposedBranch: 'feature/webhook-auth',
      targetBranch: 'main',
      commitSha: '0'.repeat(40),
      checkUrl: null,
    }
  }

  return {
    kind,
    repositoryDisplayName: 'placeholder/local-repository',
    worktreeLabel: kind === 'local-worktree' ? 'WORKTREE' : null,
    targetRef: 'HEAD',
    proposedRef: kind === 'local-committed-ref' ? 'HEAD' : 'WORKTREE',
    snapshotSha: null,
  }
}

function identityForSource(source: ReviewSourceView): ReviewIdentityView {
  if (source.kind === 'github-pull-request') {
    return {
      reviewRequestKey: `${source.repositoryFullName}#${String(source.pullRequestNumber)}`,
      sourceRepository: source.repositoryFullName,
      targetRef: source.targetBranch,
      targetHeadOid: null,
      proposedSource: source.proposedBranch,
      proposedHeadOid: source.commitSha,
      mergeTreeOid: null,
      reviewIdentity: null,
      identityUnavailableReason: 'Foundation placeholder — identity is populated in A-012.',
    }
  }

  return {
    reviewRequestKey: source.repositoryDisplayName,
    sourceRepository: source.repositoryDisplayName,
    targetRef: source.targetRef ?? 'HEAD',
    targetHeadOid: null,
    proposedSource: source.proposedRef ?? 'WORKTREE',
    proposedHeadOid: null,
    mergeTreeOid: null,
    reviewIdentity: null,
    identityUnavailableReason: 'Foundation placeholder — identity is populated in A-012.',
  }
}

export function createPlaceholderReviewRun(input: {
  attemptId: string
  gateState: ReviewRunView['gateState']
  sourceKind: ReviewRunView['source']['kind']
}): ReviewRunView {
  const source = sourceForCase(input.sourceKind)
  const repositoryDisplayName =
    source.kind === 'github-pull-request'
      ? source.repositoryFullName
      : source.repositoryDisplayName
  const createdAt = '1970-01-01T00:00:00.000Z'
  const gate: GateDecisionView = {
    gateState: input.gateState,
    blockingFingerprints: [],
    summary: 'Foundation placeholder. Full fixture data is delivered in A-012.',
    requiredCoverageComplete: false,
  }
  const summary: ReviewSummaryView = {
    attemptId: input.attemptId,
    repositoryDisplayName,
    source,
    runStatus: 'completed',
    gateState: input.gateState,
    authority:
      source.kind === 'github-pull-request' ? 'authoritative' : 'local_non_authoritative',
    publicationStatus:
      source.kind === 'github-pull-request' ? 'not_applicable' : 'not_applicable',
    bypassState: 'none',
    findingCount: 0,
    highestSeverity: null,
    durationMs: null,
    costUsd: null,
    costUnknown: true,
    provider: 'placeholder',
    model: 'placeholder',
    createdAt,
    completedAt: createdAt,
  }
  const attempt: ReviewAttemptView = {
    attemptId: input.attemptId,
    authority: summary.authority,
    gateState: input.gateState,
    trigger: 'prototype-placeholder',
    provider: summary.provider,
    model: summary.model,
    reviewPolicyVersion: placeholderPolicies.reviewPolicyVersion,
    computePolicyVersion: placeholderPolicies.computePolicyVersion,
    tokenCount: null,
    costUsd: null,
    costUnknown: true,
    startedAt: createdAt,
    durationMs: null,
  }

  return {
    attemptId: input.attemptId,
    runStatus: 'completed',
    gateState: input.gateState,
    authority: summary.authority,
    publicationStatus: summary.publicationStatus,
    bypassState: 'none',
    source,
    summary,
    gate,
    findings: [],
    coverage: emptyCoverage,
    dimensions: [],
    attempts: [attempt],
    identity: identityForSource(source),
    policies: placeholderPolicies,
    usage: emptyUsage,
    providerHealth: placeholderProviderHealth,
    availableActions: unavailableActions,
  }
}
