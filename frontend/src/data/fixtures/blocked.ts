import type { GitHubPullRequestSourceView, ReviewRunView } from '../../domain/review.ts'
import {
  BLOCKED_COST_USD,
  BLOCKED_DEMO_ATTEMPT_ID,
  BLOCKED_DURATION_MS,
  LONG_EVIDENCE_PATH,
  LONG_HASH,
} from './constants.ts'
import {
  attemptFromRun,
  githubBlockedActions,
  openaiProviderHealth,
  pipelineStages,
  reviewPolicySnapshot,
} from './shared.ts'

const createdAt = '2026-09-09T15:45:00.000Z'
const completedAt = '2026-09-09T15:47:18.000Z'

const source: GitHubPullRequestSourceView = {
  kind: 'github-pull-request',
  repositoryFullName: 'acme/payment-service',
  pullRequestNumber: 184,
  pullRequestTitle: 'Harden webhook authorization',
  authorLogin: 'ada',
  proposedBranch: 'feature/webhook-auth',
  targetBranch: 'main',
  commitSha: 'c8e21b44a09f73d1e6c5a8b7d4f0e1c2a9b8d7c6',
  checkUrl: null,
}

const snapshotIdentity = 'mtree_b7d4e1c2a9f8b0c3d6e5a1f4c8b9d0e2a3f6c7b1'

export const blockedCase: ReviewRunView = {
  attemptId: BLOCKED_DEMO_ATTEMPT_ID,
  runStatus: 'completed',
  gateState: 'blocked',
  authority: 'authoritative',
  publicationStatus: 'not_applicable',
  bypassState: 'none',
  source,
  summary: {
    attemptId: BLOCKED_DEMO_ATTEMPT_ID,
    repositoryDisplayName: 'acme/payment-service',
    source,
    runStatus: 'completed',
    gateState: 'blocked',
    authority: 'authoritative',
    publicationStatus: 'not_applicable',
    bypassState: 'none',
    findingCount: 3,
    highestSeverity: 'major',
    durationMs: BLOCKED_DURATION_MS,
    costUsd: BLOCKED_COST_USD,
    costUnknown: false,
    provider: 'openai',
    model: 'gpt-5.6',
    createdAt,
    completedAt,
  },
  gate: {
    gateState: 'blocked',
    blockingFingerprints: ['fp_9f3c1a2b_webhook_unsigned_fallback'],
    summary:
      'Review completed. One blocking security finding remains: unsigned webhook requests can still be accepted.',
    requiredCoverageComplete: true,
  },
  findings: [
    {
      fingerprint: 'fp_9f3c1a2b_webhook_unsigned_fallback',
      severity: 'major',
      evidenceBand: 'supported',
      dimensionId: 'security',
      problemStatement:
        'When the signature header is missing, the fallback branch still accepts the webhook request.',
      expectedImpact:
        'An unauthenticated caller can trigger payment-state changes on the merge candidate without a valid Stripe signature.',
      repairGuidance:
        'Reject requests that omit the signature header. Do not keep an accept-on-missing-header compatibility branch.',
      blocking: true,
      evidenceSpans: [
        {
          path: LONG_EVIDENCE_PATH,
          startLine: 74,
          endLine: 81,
          source: 'review-worktree',
          snapshotIdentity,
          changeKind: 'modified',
          quotedText:
            'if header is None:\n    logger.warning("signature header missing; accepting for compatibility")\n    return True',
        },
      ],
    },
    {
      fingerprint: 'fp_4c81de70_retention_disclosure_dup',
      severity: 'minor',
      evidenceBand: 'supported',
      dimensionId: 'maintainability',
      problemStatement: 'Retention disclosure is duplicated on two configuration paths and can drift.',
      expectedImpact:
        'Operators may see conflicting retention text depending on which compute-policy path is loaded.',
      repairGuidance:
        'Keep a single retention disclosure source and reference it from both configuration paths.',
      blocking: false,
      evidenceSpans: [
        {
          path: 'src/config/provider.py',
          startLine: 118,
          endLine: 126,
          source: 'review-worktree',
          snapshotIdentity,
          changeKind: 'modified',
          quotedText:
            'disclosure = profile.retention or DEFAULT_RETENTION_DISCLOSURE\n# duplicated below for local-cli adapter',
        },
      ],
    },
    {
      fingerprint: 'fp_b2a90e11_github_transport_mapping',
      severity: 'suggestion',
      evidenceBand: 'insufficient',
      dimensionId: 'architecture',
      problemStatement:
        'GitHub transport mapping still lives in the service entry module and is hard to review in isolation.',
      expectedImpact:
        'Webhook and Check mapping changes require loading the entire process entrypoint.',
      repairGuidance:
        'Move GitHub transport mapping out of the service entry into a dedicated adapter module.',
      blocking: false,
      evidenceSpans: [
        {
          path: 'src/server/app.py',
          startLine: 42,
          endLine: 55,
          source: 'review-worktree',
          snapshotIdentity,
          changeKind: 'modified',
          quotedText: 'app.include_router(github_webhooks.router, prefix="/github")',
        },
      ],
    },
  ],
  coverage: {
    requiredCoverage: 'complete',
    reviewedCount: 48,
    excludedCount: 2,
    missingCount: 0,
    files: [
      {
        path: LONG_EVIDENCE_PATH,
        category: 'reviewed',
        reason: null,
        rule: 'mandatory-glob: src/platform/webhooks/**',
      },
      {
        path: 'src/config/provider.py',
        category: 'reviewed',
        reason: null,
        rule: 'changed-content',
      },
      {
        path: 'src/server/app.py',
        category: 'reviewed',
        reason: null,
        rule: 'changed-content',
      },
      {
        path: 'vendor/stripe-sdk/**',
        category: 'excluded',
        reason: 'Third-party vendored code is excluded by Review Policy.',
        rule: 'excluded-glob: vendor/**',
      },
      {
        path: 'docs/internal/runbooks.md',
        category: 'excluded',
        reason: 'Documentation is optional context and was not required for this Review Policy.',
        rule: 'optional-glob: docs/**',
      },
    ],
  },
  dimensions: [
    {
      dimensionId: 'security',
      status: 'completed',
      elapsedMs: 38_400,
      findingCount: 1,
      blockingFindingCount: 1,
    },
    {
      dimensionId: 'correctness',
      status: 'completed',
      elapsedMs: 21_100,
      findingCount: 0,
      blockingFindingCount: 0,
    },
    {
      dimensionId: 'architecture',
      status: 'completed',
      elapsedMs: 18_600,
      findingCount: 1,
      blockingFindingCount: 0,
    },
    {
      dimensionId: 'maintainability',
      status: 'completed',
      elapsedMs: 16_200,
      findingCount: 1,
      blockingFindingCount: 0,
    },
  ],
  pipeline: pipelineStages('publish'),
  failure: null,
  attempts: [],
  identity: {
    reviewRequestKey: 'github:acme/payment-service#184',
    sourceRepository: 'acme/payment-service',
    targetRef: 'main',
    targetHeadOid: 'a3f8c1d92e4b70aa18c6d5e4f0b91c27d8e4a1b2',
    proposedSource: 'feature/webhook-auth',
    proposedHeadOid: 'c8e21b44a09f73d1e6c5a8b7d4f0e1c2a9b8d7c6',
    mergeTreeOid: 'b7d4e1c2a9f8b0c3d6e5a1f4c8b9d0e2a3f6c7b1',
    reviewIdentity: LONG_HASH,
    identityUnavailableReason: null,
  },
  policies: reviewPolicySnapshot,
  usage: {
    estimatedCostUsd: 0.4,
    actualCostUsd: BLOCKED_COST_USD,
    costUnknown: false,
    unknownCostRecordCount: 0,
    inputTokens: 32_800,
    outputTokens: 4_200,
    calls: [
      {
        ordinal: 1,
        dimensionId: 'security',
        provider: 'openai',
        model: 'gpt-5.6',
        elapsedMs: 18_400,
        usageKind: 'dimension-review',
        inputTokens: 12_400,
        outputTokens: 1_600,
        costUsd: 0.16,
        costUnknown: false,
      },
      {
        ordinal: 2,
        dimensionId: 'correctness',
        provider: 'openai',
        model: 'gpt-5.6',
        elapsedMs: 11_200,
        usageKind: 'dimension-review',
        inputTokens: 8_100,
        outputTokens: 900,
        costUsd: 0.09,
        costUnknown: false,
      },
      {
        ordinal: 3,
        dimensionId: 'architecture',
        provider: 'openai',
        model: 'gpt-5.6',
        elapsedMs: 9_800,
        usageKind: 'dimension-review',
        inputTokens: 6_400,
        outputTokens: 800,
        costUsd: 0.08,
        costUnknown: false,
      },
      {
        ordinal: 4,
        dimensionId: 'maintainability',
        provider: 'openai',
        model: 'gpt-5.6',
        elapsedMs: 8_600,
        usageKind: 'dimension-review',
        inputTokens: 5_900,
        outputTokens: 900,
        costUsd: 0.09,
        costUnknown: false,
      },
    ],
  },
  providerHealth: openaiProviderHealth,
  availableActions: githubBlockedActions(),
}

blockedCase.attempts = [attemptFromRun(blockedCase, 'github-pull-request')]
