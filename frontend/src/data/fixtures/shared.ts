import type {
  AvailableReviewActionsView,
  PipelineStageName,
  PipelineStageStatus,
  PipelineStageView,
  PolicySnapshotView,
  ProviderHealthView,
  ReviewAttemptView,
  ReviewRunView,
} from '../../domain/review.ts'
import { PIPELINE_STAGE_ORDER } from '../../domain/review.ts'

export const reviewPolicySnapshot: PolicySnapshotView = {
  reviewPolicyName: 'default-review',
  reviewPolicyVersion: '1.3.0',
  reviewPolicySha256: '6b1f0c8e4a9d2b7c3e5f1a8d0c6b4e9f2a7c1d5e8b3f0a6c9d2e4b7f1a5c8e3d',
  computePolicyName: 'openai-gpt-5.6',
  computePolicyVersion: '2.1.0',
  computePolicySha256: 'a9c4e2b7d1f6a3c8e0b5d9f2a7c1e4b8d3f6a0c5e9b2d7f1a4c8e3b6d0f5a2c7',
  dataDestination: 'OpenAI API (United States). Exact retention is provider-stated, not independently verified.',
  retentionDisclosure:
    'Provider-stated retention is 30 days for API abuse monitoring. Worktree Review does not independently verify this.',
  providerConfigurationFingerprint: 'pcfg_openai_api_2026_09_01',
}

export const openaiProviderHealth: ProviderHealthView = {
  profileName: 'openai-production',
  status: 'healthy',
  observedAt: '2026-09-09T14:12:00.000Z',
}

export function localActions(): AvailableReviewActionsView {
  return {
    retry: {
      visible: true,
      enabled: false,
      disabledReason:
        'Retry creates a new local attempt and does not change a standing decision. This Pre-Alpha prototype does not submit Retry.',
    },
    bypass: {
      visible: false,
      enabled: false,
      disabledReason: 'Bypass is not available for local one-shot results.',
    },
    openCheck: {
      visible: false,
      enabled: false,
      disabledReason: 'GitHub Checks do not apply to local reviews.',
    },
    openSessionInsight: {
      visible: true,
      enabled: false,
      disabledReason: 'Session Insight is not connected in this Pre-Alpha prototype.',
    },
  }
}

export function githubBlockedActions(): AvailableReviewActionsView {
  return {
    retry: {
      visible: true,
      enabled: false,
      disabledReason:
        'Retry will create a new authoritative attempt and temporarily revoke the current standing decision until the review completes. This Pre-Alpha prototype does not submit a GitHub Checks requested action.',
    },
    bypass: {
      visible: true,
      enabled: false,
      disabledReason:
        'Bypass means accepting the risk. It does not mean the finding was resolved. This Pre-Alpha prototype does not submit Bypass, and no GitHub actor is authenticated.',
    },
    openCheck: {
      visible: true,
      enabled: false,
      disabledReason: 'GitHub Checks are not connected in this Pre-Alpha prototype.',
    },
    openSessionInsight: {
      visible: true,
      enabled: false,
      disabledReason: 'Session Insight is not connected in this Pre-Alpha prototype.',
    },
  }
}

export function pipelineStages(
  through: PipelineStageName,
  failed?: { stage: PipelineStageName; safeError: string },
): PipelineStageView[] {
  const stopIndex = PIPELINE_STAGE_ORDER.indexOf(through)
  return PIPELINE_STAGE_ORDER.map((stage, index) => {
    let status: PipelineStageStatus = 'not-started'
    let safeError: string | null = null
    if (failed && stage === failed.stage) {
      status = 'failed'
      safeError = failed.safeError
    } else if (index <= stopIndex && !(failed && index >= PIPELINE_STAGE_ORDER.indexOf(failed.stage))) {
      status = 'completed'
    }
    return {
      stage,
      status,
      elapsedMs: status === 'completed' ? 1_200 : status === 'failed' ? 800 : null,
      safeError,
    }
  })
}

export function attemptFromRun(
  run: Pick<
    ReviewRunView,
    'attemptId' | 'authority' | 'gateState' | 'summary' | 'policies' | 'usage'
  >,
  trigger: string,
): ReviewAttemptView {
  return {
    attemptId: run.attemptId,
    authority: run.authority,
    gateState: run.gateState,
    trigger,
    provider: run.summary.provider,
    model: run.summary.model,
    reviewPolicyVersion: run.policies.reviewPolicyVersion,
    computePolicyVersion: run.policies.computePolicyVersion,
    tokenCount:
      run.usage.inputTokens === null && run.usage.outputTokens === null
        ? null
        : (run.usage.inputTokens ?? 0) + (run.usage.outputTokens ?? 0),
    costUsd: run.usage.actualCostUsd,
    costUnknown: run.usage.costUnknown,
    startedAt: run.summary.createdAt,
    durationMs: run.summary.durationMs,
  }
}
