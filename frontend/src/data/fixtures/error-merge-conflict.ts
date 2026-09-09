import type { LocalReviewSourceView, ReviewRunView } from '../../domain/review.ts'
import {
  ERROR_DEMO_ATTEMPT_ID,
  ERROR_DURATION_MS,
  LONG_EVIDENCE_PATH,
  MERGE_CONFLICT_ERROR,
} from './constants.ts'
import { attemptFromRun, localActions, openaiProviderHealth, pipelineStages, reviewPolicySnapshot } from './shared.ts'

const createdAt = '2026-09-09T15:50:00.000Z'
const completedAt = '2026-09-09T15:50:04.200Z'

const source: LocalReviewSourceView = {
  kind: 'local-committed-ref',
  repositoryDisplayName: 'acme/demo-invalid-config',
  worktreeLabel: null,
  targetRef: 'main',
  proposedRef: 'feature/broken-merge',
  snapshotSha: null,
}

export const errorMergeConflictCase: ReviewRunView = {
  attemptId: ERROR_DEMO_ATTEMPT_ID,
  runStatus: 'failed',
  gateState: 'error',
  authority: 'local_non_authoritative',
  publicationStatus: 'not_applicable',
  bypassState: 'none',
  source,
  summary: {
    attemptId: ERROR_DEMO_ATTEMPT_ID,
    repositoryDisplayName: 'acme/demo-invalid-config',
    source,
    runStatus: 'failed',
    gateState: 'error',
    authority: 'local_non_authoritative',
    publicationStatus: 'not_applicable',
    bypassState: 'none',
    findingCount: 0,
    highestSeverity: null,
    durationMs: ERROR_DURATION_MS,
    costUsd: null,
    costUnknown: true,
    provider: 'openai',
    model: 'gpt-5.6',
    createdAt,
    completedAt,
  },
  gate: {
    gateState: 'error',
    blockingFingerprints: [],
    summary:
      'Review did not finish. Merge candidate construction failed, so Gate is Error and Review Identity is unavailable.',
    requiredCoverageComplete: false,
  },
  findings: [],
  coverage: {
    requiredCoverage: 'incomplete',
    reviewedCount: 0,
    excludedCount: 0,
    missingCount: 0,
    files: [
      {
        path: LONG_EVIDENCE_PATH,
        category: 'unreviewable',
        reason: 'Changed content could not be reviewed because the merge tree was not constructed.',
        rule: 'merge-candidate-required',
      },
    ],
  },
  dimensions: [
    { dimensionId: 'security', status: 'not-started', elapsedMs: null, findingCount: 0, blockingFindingCount: 0 },
    { dimensionId: 'correctness', status: 'not-started', elapsedMs: null, findingCount: 0, blockingFindingCount: 0 },
    { dimensionId: 'architecture', status: 'not-started', elapsedMs: null, findingCount: 0, blockingFindingCount: 0 },
    {
      dimensionId: 'maintainability',
      status: 'not-started',
      elapsedMs: null,
      findingCount: 0,
      blockingFindingCount: 0,
    },
  ],
  pipeline: pipelineStages('derive-identity', {
    stage: 'construct-merge',
    safeError: MERGE_CONFLICT_ERROR,
  }),
  failure: {
    stage: 'construct-merge',
    category: 'merge_conflict',
    safeDetail: MERGE_CONFLICT_ERROR,
  },
  attempts: [],
  identity: {
    reviewRequestKey: 'local:acme/demo-invalid-config:main:feature/broken-merge',
    sourceRepository: 'acme/demo-invalid-config',
    targetRef: 'main',
    targetHeadOid: '7b2e9c14a8d50f6c1e3a7b4d0c9f2e8a5d1c6b30',
    proposedSource: 'feature/broken-merge',
    proposedHeadOid: 'f0c8a5d3b1e79a4c6d2f8b0e5a1c7d9f3b6e4a20',
    mergeTreeOid: null,
    reviewIdentity: null,
    identityUnavailableReason: 'Review identity unavailable — merge candidate was not constructed.',
  },
  policies: reviewPolicySnapshot,
  usage: {
    estimatedCostUsd: null,
    actualCostUsd: null,
    costUnknown: true,
    unknownCostRecordCount: 1,
    inputTokens: null,
    outputTokens: null,
    calls: [],
  },
  providerHealth: openaiProviderHealth,
  availableActions: localActions(),
}

errorMergeConflictCase.attempts = [attemptFromRun(errorMergeConflictCase, 'local-committed-ref')]
