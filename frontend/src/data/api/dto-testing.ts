/**
 * Test helpers that convert frozen View Models back into wire DTOs, so API
 * client and mapper tests exercise realistic payloads. Not part of the app
 * bundle; imported by test files only.
 */
import type { OverviewView } from '../../domain/overview.ts'
import type {
  GitHubPullRequestSourceView,
  LocalReviewSourceView,
  ReviewRunView,
  ReviewSourceView,
  ReviewSummaryView,
} from '../../domain/review.ts'
import type {
  GitHubSourceDto,
  LocalSourceDto,
  OverviewDto,
  ReviewRunDto,
  ReviewSourceDto,
  ReviewSummaryDto,
} from './dto.ts'

export function sourceToDto(source: ReviewSourceView): ReviewSourceDto {
  if (source.kind === 'github-pull-request') {
    const github = source as GitHubPullRequestSourceView
    const dto: GitHubSourceDto = {
      kind: source.kind,
      repository_full_name: github.repositoryFullName,
      pull_request_number: github.pullRequestNumber,
      pull_request_title: github.pullRequestTitle,
      author_login: github.authorLogin,
      proposed_branch: github.proposedBranch,
      target_branch: github.targetBranch,
      commit_sha: github.commitSha,
      check_url: github.checkUrl,
    }
    return dto
  }
  const local = source as LocalReviewSourceView
  const dto: LocalSourceDto = {
    kind: source.kind,
    repository_display_name: local.repositoryDisplayName,
    worktree_label: local.worktreeLabel,
    target_ref: local.targetRef,
    proposed_ref: local.proposedRef,
    snapshot_sha: local.snapshotSha,
  }
  return dto
}

export function summaryToDto(summary: ReviewSummaryView): ReviewSummaryDto {
  return {
    attempt_id: summary.attemptId,
    repository_display_name: summary.repositoryDisplayName,
    source: sourceToDto(summary.source),
    run_status: summary.runStatus,
    gate_state: summary.gateState,
    authority: summary.authority,
    publication_status: summary.publicationStatus,
    bypass_state: summary.bypassState,
    finding_count: summary.findingCount,
    highest_severity: summary.highestSeverity,
    duration_ms: summary.durationMs,
    cost_usd: summary.costUsd,
    cost_unknown: summary.costUnknown,
    provider: summary.provider,
    model: summary.model,
    created_at: summary.createdAt,
    completed_at: summary.completedAt,
  }
}

export function runToDto(run: ReviewRunView): ReviewRunDto {
  return {
    attempt_id: run.attemptId,
    run_status: run.runStatus,
    gate_state: run.gateState,
    authority: run.authority,
    publication_status: run.publicationStatus,
    bypass_state: run.bypassState,
    source: sourceToDto(run.source),
    summary: summaryToDto(run.summary),
    gate: {
      gate_state: run.gate.gateState,
      blocking_fingerprints: run.gate.blockingFingerprints,
      summary: run.gate.summary,
      required_coverage_complete: run.gate.requiredCoverageComplete,
    },
    findings: run.findings.map((finding) => ({
      fingerprint: finding.fingerprint,
      severity: finding.severity,
      evidence_band: finding.evidenceBand,
      dimension_id: finding.dimensionId,
      problem_statement: finding.problemStatement,
      expected_impact: finding.expectedImpact,
      repair_guidance: finding.repairGuidance,
      evidence_spans: finding.evidenceSpans.map((span) => ({
        path: span.path,
        start_line: span.startLine,
        end_line: span.endLine,
        source: span.source,
        snapshot_identity: span.snapshotIdentity,
        change_kind: span.changeKind,
        quoted_text: span.quotedText,
      })),
      blocking: finding.blocking,
    })),
    coverage: {
      required_coverage: run.coverage.requiredCoverage,
      reviewed_count: run.coverage.reviewedCount,
      excluded_count: run.coverage.excludedCount,
      missing_count: run.coverage.missingCount,
      files: run.coverage.files.map((file) => ({
        path: file.path,
        category: file.category,
        reason: file.reason,
        rule: file.rule,
      })),
    },
    dimensions: run.dimensions.map((dimension) => ({
      dimension_id: dimension.dimensionId,
      status: dimension.status,
      elapsed_ms: dimension.elapsedMs,
      finding_count: dimension.findingCount,
      blocking_finding_count: dimension.blockingFindingCount,
    })),
    pipeline: run.pipeline.map((stage) => ({
      stage: stage.stage,
      status: stage.status,
      elapsed_ms: stage.elapsedMs,
      safe_error: stage.safeError,
    })),
    failure:
      run.failure === null
        ? null
        : {
            stage: run.failure.stage,
            category: run.failure.category,
            safe_detail: run.failure.safeDetail,
          },
    attempts: run.attempts.map((attempt) => ({
      attempt_id: attempt.attemptId,
      authority: attempt.authority,
      gate_state: attempt.gateState,
      trigger: attempt.trigger,
      provider: attempt.provider,
      model: attempt.model,
      review_policy_version: attempt.reviewPolicyVersion,
      compute_policy_version: attempt.computePolicyVersion,
      token_count: attempt.tokenCount,
      cost_usd: attempt.costUsd,
      cost_unknown: attempt.costUnknown,
      started_at: attempt.startedAt,
      duration_ms: attempt.durationMs,
    })),
    identity: {
      review_request_key: run.identity.reviewRequestKey,
      source_repository: run.identity.sourceRepository,
      target_ref: run.identity.targetRef,
      target_head_oid: run.identity.targetHeadOid,
      proposed_source: run.identity.proposedSource,
      proposed_head_oid: run.identity.proposedHeadOid,
      merge_tree_oid: run.identity.mergeTreeOid,
      review_identity: run.identity.reviewIdentity,
      identity_unavailable_reason: run.identity.identityUnavailableReason,
    },
    policies: {
      review_policy_name: run.policies.reviewPolicyName,
      review_policy_version: run.policies.reviewPolicyVersion,
      review_policy_sha256: run.policies.reviewPolicySha256,
      compute_policy_name: run.policies.computePolicyName,
      compute_policy_version: run.policies.computePolicyVersion,
      compute_policy_sha256: run.policies.computePolicySha256,
      data_destination: run.policies.dataDestination,
      retention_disclosure: run.policies.retentionDisclosure,
      provider_configuration_fingerprint: run.policies.providerConfigurationFingerprint,
    },
    usage: {
      estimated_cost_usd: run.usage.estimatedCostUsd,
      actual_cost_usd: run.usage.actualCostUsd,
      cost_unknown: run.usage.costUnknown,
      unknown_cost_record_count: run.usage.unknownCostRecordCount,
      input_tokens: run.usage.inputTokens,
      output_tokens: run.usage.outputTokens,
      calls: run.usage.calls.map((call) => ({
        ordinal: call.ordinal,
        dimension_id: call.dimensionId,
        provider: call.provider,
        model: call.model,
        elapsed_ms: call.elapsedMs,
        usage_kind: call.usageKind,
        input_tokens: call.inputTokens,
        output_tokens: call.outputTokens,
        cost_usd: call.costUsd,
        cost_unknown: call.costUnknown,
      })),
    },
    provider_health: {
      profile_name: run.providerHealth.profileName,
      status: run.providerHealth.status,
      observed_at: run.providerHealth.observedAt,
    },
    available_actions: {
      retry: {
        visible: run.availableActions.retry.visible,
        enabled: run.availableActions.retry.enabled,
        disabled_reason: run.availableActions.retry.disabledReason,
      },
      bypass: {
        visible: run.availableActions.bypass.visible,
        enabled: run.availableActions.bypass.enabled,
        disabled_reason: run.availableActions.bypass.disabledReason,
      },
      open_check: {
        visible: run.availableActions.openCheck.visible,
        enabled: run.availableActions.openCheck.enabled,
        disabled_reason: run.availableActions.openCheck.disabledReason,
      },
      open_session_insight: {
        visible: run.availableActions.openSessionInsight.visible,
        enabled: run.availableActions.openSessionInsight.enabled,
        disabled_reason: run.availableActions.openSessionInsight.disabledReason,
      },
    },
  }
}

export function overviewToDto(overview: OverviewView): OverviewDto {
  return {
    attention: overview.attention.map(summaryToDto),
    active: overview.active.map(summaryToDto),
    recent: overview.recent.map(summaryToDto),
    stats: {
      attempt_count: overview.stats.attemptCount,
      passed_count: overview.stats.passedCount,
      blocked_count: overview.stats.blockedCount,
      error_count: overview.stats.errorCount,
      gate_pass_rate: overview.stats.gatePassRate,
      error_rate: overview.stats.errorRate,
      average_duration_ms: overview.stats.averageDurationMs,
      known_cost_usd: overview.stats.knownCostUsd,
      unknown_cost_record_count: overview.stats.unknownCostRecordCount,
      known_input_tokens: overview.stats.knownInputTokens,
      known_output_tokens: overview.stats.knownOutputTokens,
    },
    gate_trend: overview.gateTrend.map((point) => ({
      date: point.date,
      passed: point.passed,
      blocked: point.blocked,
      error: point.error,
      in_progress: point.inProgress,
    })),
    finding_severity: overview.findingSeverity.map((entry) => ({
      severity: entry.severity,
      count: entry.count,
    })),
    dimension_health: overview.dimensionHealth.map((dimension) => ({
      dimension_id: dimension.dimensionId,
      completed_count: dimension.completedCount,
      failed_count: dimension.failedCount,
      average_elapsed_ms: dimension.averageElapsedMs,
    })),
    policy_usage: overview.policyUsage.map((policy) => ({
      review_policy_version: policy.reviewPolicyVersion,
      review_count: policy.reviewCount,
      blocked_count: policy.blockedCount,
      error_count: policy.errorCount,
    })),
    provider_health: overview.providerHealth.map((health) => ({
      profile_name: health.profileName,
      status: health.status,
      observed_at: health.observedAt,
    })),
    session_insight: {
      state: overview.sessionInsight.state,
      current_attempt_id: overview.sessionInsight.currentAttemptId,
      child_session_count: overview.sessionInsight.childSessionCount,
      last_probe_at: overview.sessionInsight.lastProbeAt,
    },
  }
}
