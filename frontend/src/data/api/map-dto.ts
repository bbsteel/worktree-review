/**
 * Strict DTO → View Model mapping. Unknown enum values and missing fields
 * throw DtoValidationError — the UI must never guess at gate, authority or
 * severity semantics from an unrecognized wire value (fail closed).
 */
import type {
  OverviewStatsView,
  OverviewView,
  SessionInsightConnectionState,
} from '../../domain/overview.ts'
import type {
  Authority,
  BypassState,
  CoverageCategory,
  DimensionStatus,
  EvidenceBand,
  EvidenceSpanView,
  FindingSeverity,
  GateState,
  PublicationStatus,
  ReviewFindingView,
  PipelineStageStatus,
  ReviewRunView,
  ReviewSourceView,
  ReviewSummaryView,
  RunStatus,
} from '../../domain/review.ts'
import { PIPELINE_STAGE_ORDER } from '../../domain/review.ts'
import type {
  CoverageDto,
  DimensionDto,
  EvidenceSpanDto,
  FindingDto,
  OverviewDto,
  ReviewRunDto,
  ReviewSummaryDto,
  UsageDto,
} from './dto.ts'

export class DtoValidationError extends Error {
  readonly path: string

  constructor(path: string, reason: string) {
    super(`Invalid DTO at ${path}: ${reason}`)
    this.name = 'DtoValidationError'
    this.path = path
  }
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new DtoValidationError(path, 'expected an object')
  }
  return value as Record<string, unknown>
}

function str(value: unknown, path: string): string {
  if (typeof value !== 'string') {
    throw new DtoValidationError(path, 'expected a string')
  }
  return value
}

function strOrNull(value: unknown, path: string): string | null {
  if (value === null) {
    return null
  }
  return str(value, path)
}

function num(value: unknown, path: string): number {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new DtoValidationError(path, 'expected a number')
  }
  return value
}

function numOrNull(value: unknown, path: string): number | null {
  if (value === null) {
    return null
  }
  return num(value, path)
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') {
    throw new DtoValidationError(path, 'expected a boolean')
  }
  return value
}

function list(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new DtoValidationError(path, 'expected an array')
  }
  return value
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  const raw = str(value, path)
  if (!allowed.includes(raw as T)) {
    throw new DtoValidationError(path, `unknown value "${raw}"`)
  }
  return raw as T
}

const RUN_STATUSES: readonly RunStatus[] = [
  'queued',
  'preparing',
  'running',
  'completed',
  'failed',
  'interrupted',
]
const GATE_STATES: readonly GateState[] = [
  'awaiting_review',
  'in_progress',
  'passed',
  'passed_with_bypass',
  'blocked',
  'error',
]
const AUTHORITIES: readonly Authority[] = [
  'local_non_authoritative',
  'authoritative',
  'superseded',
  'audit_only',
]
const PUBLICATION_STATUSES: readonly PublicationStatus[] = [
  'not_applicable',
  'queued',
  'in_progress',
  'published',
  'failed',
  'superseded',
]
const BYPASS_STATES: readonly BypassState[] = ['none', 'active', 'invalidated']
const SEVERITIES: readonly FindingSeverity[] = ['critical', 'major', 'minor', 'suggestion']
const EVIDENCE_BANDS: readonly EvidenceBand[] = ['supported', 'insufficient']
const DIMENSION_STATUSES: readonly DimensionStatus[] = [
  'not-started',
  'running',
  'completed',
  'failed',
]
const COVERAGE_CATEGORIES: readonly CoverageCategory[] = [
  'reviewed',
  'mandatory-missing',
  'optional-missing',
  'excluded',
  'unreviewable',
]
const PIPELINE_STAGE_STATUSES: readonly PipelineStageStatus[] = [
  'not-started',
  'running',
  'completed',
  'failed',
]
const SESSION_INSIGHT_STATES: readonly SessionInsightConnectionState[] = [
  'connected',
  'disconnected',
  'incompatible',
  'disabled',
]
const LOCAL_SOURCE_KINDS = ['local-worktree', 'local-recent-commits', 'local-committed-ref'] as const

function mapSource(raw: unknown, path: string): ReviewSourceView {
  const dto = record(raw, path)
  const kind = str(dto.kind, `${path}.kind`)
  if (kind === 'github-pull-request') {
    return {
      kind,
      repositoryFullName: str(dto.repository_full_name, `${path}.repository_full_name`),
      pullRequestNumber: num(dto.pull_request_number, `${path}.pull_request_number`),
      pullRequestTitle: str(dto.pull_request_title, `${path}.pull_request_title`),
      authorLogin: str(dto.author_login, `${path}.author_login`),
      proposedBranch: str(dto.proposed_branch, `${path}.proposed_branch`),
      targetBranch: str(dto.target_branch, `${path}.target_branch`),
      commitSha: str(dto.commit_sha, `${path}.commit_sha`),
      checkUrl: strOrNull(dto.check_url, `${path}.check_url`),
    }
  }
  return {
    kind: oneOf(dto.kind, LOCAL_SOURCE_KINDS, `${path}.kind`),
    repositoryDisplayName: str(dto.repository_display_name, `${path}.repository_display_name`),
    worktreeLabel: strOrNull(dto.worktree_label, `${path}.worktree_label`),
    targetRef: strOrNull(dto.target_ref, `${path}.target_ref`),
    proposedRef: strOrNull(dto.proposed_ref, `${path}.proposed_ref`),
    snapshotSha: strOrNull(dto.snapshot_sha, `${path}.snapshot_sha`),
  }
}

export function mapReviewSummaryDto(raw: unknown, path = 'summary'): ReviewSummaryView {
  const dto = record(raw, path) as unknown as ReviewSummaryDto
  return {
    attemptId: str(dto.attempt_id, `${path}.attempt_id`),
    repositoryDisplayName: str(dto.repository_display_name, `${path}.repository_display_name`),
    source: mapSource(dto.source, `${path}.source`),
    runStatus: oneOf(dto.run_status, RUN_STATUSES, `${path}.run_status`),
    gateState: oneOf(dto.gate_state, GATE_STATES, `${path}.gate_state`),
    authority: oneOf(dto.authority, AUTHORITIES, `${path}.authority`),
    publicationStatus: oneOf(dto.publication_status, PUBLICATION_STATUSES, `${path}.publication_status`),
    bypassState: oneOf(dto.bypass_state, BYPASS_STATES, `${path}.bypass_state`),
    findingCount: num(dto.finding_count, `${path}.finding_count`),
    highestSeverity:
      dto.highest_severity === null
        ? null
        : oneOf(dto.highest_severity, SEVERITIES, `${path}.highest_severity`),
    durationMs: numOrNull(dto.duration_ms, `${path}.duration_ms`),
    costUsd: numOrNull(dto.cost_usd, `${path}.cost_usd`),
    costUnknown: bool(dto.cost_unknown, `${path}.cost_unknown`),
    provider: str(dto.provider, `${path}.provider`),
    model: str(dto.model, `${path}.model`),
    createdAt: str(dto.created_at, `${path}.created_at`),
    completedAt: strOrNull(dto.completed_at, `${path}.completed_at`),
  }
}

function mapEvidenceSpan(dto: EvidenceSpanDto, path: string): EvidenceSpanView {
  return {
    path: str(dto.path, `${path}.path`),
    startLine: num(dto.start_line, `${path}.start_line`),
    endLine: num(dto.end_line, `${path}.end_line`),
    source: str(dto.source, `${path}.source`),
    snapshotIdentity: str(dto.snapshot_identity, `${path}.snapshot_identity`),
    changeKind: str(dto.change_kind, `${path}.change_kind`),
    quotedText: str(dto.quoted_text, `${path}.quoted_text`),
  }
}

function mapFinding(raw: unknown, index: number): ReviewFindingView {
  const path = `findings[${index}]`
  const dto = record(raw, path) as unknown as FindingDto
  return {
    fingerprint: str(dto.fingerprint, `${path}.fingerprint`),
    severity: oneOf(dto.severity, SEVERITIES, `${path}.severity`),
    evidenceBand: oneOf(dto.evidence_band, EVIDENCE_BANDS, `${path}.evidence_band`),
    dimensionId: str(dto.dimension_id, `${path}.dimension_id`),
    problemStatement: str(dto.problem_statement, `${path}.problem_statement`),
    expectedImpact: str(dto.expected_impact, `${path}.expected_impact`),
    repairGuidance: str(dto.repair_guidance, `${path}.repair_guidance`),
    evidenceSpans: list(dto.evidence_spans, `${path}.evidence_spans`).map((span, spanIndex) =>
      mapEvidenceSpan(record(span, `${path}.evidence_spans[${spanIndex}]`) as unknown as EvidenceSpanDto, `${path}.evidence_spans[${spanIndex}]`),
    ),
    blocking: bool(dto.blocking, `${path}.blocking`),
  }
}

function mapActionCapability(raw: unknown, path: string) {
  const dto = record(raw, path)
  return {
    visible: bool(dto.visible, `${path}.visible`),
    enabled: bool(dto.enabled, `${path}.enabled`),
    disabledReason: strOrNull(dto.disabled_reason, `${path}.disabled_reason`),
  }
}

export function mapReviewRunDto(raw: unknown): ReviewRunView {
  const dto = record(raw, 'run') as unknown as ReviewRunDto
  const gateDto = record(dto.gate, 'gate')
  const coverage = record(dto.coverage, 'coverage') as unknown as CoverageDto
  const identity = record(dto.identity, 'identity')
  const policies = record(dto.policies, 'policies')
  const usage = record(dto.usage, 'usage') as unknown as UsageDto
  const health = record(dto.provider_health, 'provider_health')
  const actions = record(dto.available_actions, 'available_actions')

  return {
    attemptId: str(dto.attempt_id, 'run.attempt_id'),
    runStatus: oneOf(dto.run_status, RUN_STATUSES, 'run.run_status'),
    gateState: oneOf(dto.gate_state, GATE_STATES, 'run.gate_state'),
    authority: oneOf(dto.authority, AUTHORITIES, 'run.authority'),
    publicationStatus: oneOf(dto.publication_status, PUBLICATION_STATUSES, 'run.publication_status'),
    bypassState: oneOf(dto.bypass_state, BYPASS_STATES, 'run.bypass_state'),
    source: mapSource(dto.source, 'run.source'),
    summary: mapReviewSummaryDto(dto.summary),
    gate: {
      gateState: oneOf(gateDto.gate_state, GATE_STATES, 'gate.gate_state'),
      blockingFingerprints: list(gateDto.blocking_fingerprints, 'gate.blocking_fingerprints').map(
        (fingerprint, index) => str(fingerprint, `gate.blocking_fingerprints[${index}]`),
      ),
      summary: str(gateDto.summary, 'gate.summary'),
      requiredCoverageComplete: bool(
        gateDto.required_coverage_complete,
        'gate.required_coverage_complete',
      ),
    },
    findings: list(dto.findings, 'run.findings').map((finding, index) => mapFinding(finding, index)),
    coverage: {
      requiredCoverage: oneOf(
        coverage.required_coverage,
        ['complete', 'incomplete'] as const,
        'coverage.required_coverage',
      ),
      reviewedCount: num(coverage.reviewed_count, 'coverage.reviewed_count'),
      excludedCount: num(coverage.excluded_count, 'coverage.excluded_count'),
      missingCount: num(coverage.missing_count, 'coverage.missing_count'),
      files: list(coverage.files, 'coverage.files').map((rawFile, index) => {
        const file = record(rawFile, `coverage.files[${index}]`)
        return {
          path: str(file.path, `coverage.files[${index}].path`),
          category: oneOf(file.category, COVERAGE_CATEGORIES, `coverage.files[${index}].category`),
          reason: strOrNull(file.reason, `coverage.files[${index}].reason`),
          rule: strOrNull(file.rule, `coverage.files[${index}].rule`),
        }
      }),
    },
    dimensions: list(dto.dimensions, 'run.dimensions').map((rawDimension, index) => {
      const dimension = record(rawDimension, `dimensions[${index}]`) as unknown as DimensionDto
      return {
        dimensionId: str(dimension.dimension_id, `dimensions[${index}].dimension_id`),
        status: oneOf(dimension.status, DIMENSION_STATUSES, `dimensions[${index}].status`),
        elapsedMs: numOrNull(dimension.elapsed_ms, `dimensions[${index}].elapsed_ms`),
        findingCount: num(dimension.finding_count, `dimensions[${index}].finding_count`),
        blockingFindingCount: num(
          dimension.blocking_finding_count,
          `dimensions[${index}].blocking_finding_count`,
        ),
      }
    }),
    pipeline: list(dto.pipeline, 'run.pipeline').map((rawStage, index) => {
      const stage = record(rawStage, `pipeline[${index}]`)
      return {
        stage: oneOf(stage.stage, PIPELINE_STAGE_ORDER, `pipeline[${index}].stage`),
        status: oneOf(stage.status, PIPELINE_STAGE_STATUSES, `pipeline[${index}].status`),
        elapsedMs: numOrNull(stage.elapsed_ms, `pipeline[${index}].elapsed_ms`),
        safeError: strOrNull(stage.safe_error, `pipeline[${index}].safe_error`),
      }
    }),
    failure:
      dto.failure === null
        ? null
        : (() => {
            const failure = record(dto.failure, 'failure')
            return {
              stage: oneOf(failure.stage, PIPELINE_STAGE_ORDER, 'failure.stage'),
              category: str(failure.category, 'failure.category'),
              safeDetail: str(failure.safe_detail, 'failure.safe_detail'),
            }
          })(),
    attempts: list(dto.attempts, 'run.attempts').map((rawAttempt, index) => {
      const attempt = record(rawAttempt, `attempts[${index}]`)
      return {
        attemptId: str(attempt.attempt_id, `attempts[${index}].attempt_id`),
        authority: oneOf(attempt.authority, AUTHORITIES, `attempts[${index}].authority`),
        gateState: oneOf(attempt.gate_state, GATE_STATES, `attempts[${index}].gate_state`),
        trigger: str(attempt.trigger, `attempts[${index}].trigger`),
        provider: str(attempt.provider, `attempts[${index}].provider`),
        model: str(attempt.model, `attempts[${index}].model`),
        reviewPolicyVersion: str(
          attempt.review_policy_version,
          `attempts[${index}].review_policy_version`,
        ),
        computePolicyVersion: str(
          attempt.compute_policy_version,
          `attempts[${index}].compute_policy_version`,
        ),
        tokenCount: numOrNull(attempt.token_count, `attempts[${index}].token_count`),
        costUsd: numOrNull(attempt.cost_usd, `attempts[${index}].cost_usd`),
        costUnknown: bool(attempt.cost_unknown, `attempts[${index}].cost_unknown`),
        startedAt: str(attempt.started_at, `attempts[${index}].started_at`),
        durationMs: numOrNull(attempt.duration_ms, `attempts[${index}].duration_ms`),
      }
    }),
    identity: {
      reviewRequestKey: str(identity.review_request_key, 'identity.review_request_key'),
      sourceRepository: str(identity.source_repository, 'identity.source_repository'),
      targetRef: str(identity.target_ref, 'identity.target_ref'),
      targetHeadOid: strOrNull(identity.target_head_oid, 'identity.target_head_oid'),
      proposedSource: str(identity.proposed_source, 'identity.proposed_source'),
      proposedHeadOid: strOrNull(identity.proposed_head_oid, 'identity.proposed_head_oid'),
      mergeTreeOid: strOrNull(identity.merge_tree_oid, 'identity.merge_tree_oid'),
      reviewIdentity: strOrNull(identity.review_identity, 'identity.review_identity'),
      identityUnavailableReason: strOrNull(
        identity.identity_unavailable_reason,
        'identity.identity_unavailable_reason',
      ),
    },
    policies: {
      reviewPolicyName: str(policies.review_policy_name, 'policies.review_policy_name'),
      reviewPolicyVersion: str(policies.review_policy_version, 'policies.review_policy_version'),
      reviewPolicySha256: str(policies.review_policy_sha256, 'policies.review_policy_sha256'),
      computePolicyName: str(policies.compute_policy_name, 'policies.compute_policy_name'),
      computePolicyVersion: str(policies.compute_policy_version, 'policies.compute_policy_version'),
      computePolicySha256: str(policies.compute_policy_sha256, 'policies.compute_policy_sha256'),
      dataDestination: str(policies.data_destination, 'policies.data_destination'),
      retentionDisclosure: str(policies.retention_disclosure, 'policies.retention_disclosure'),
      providerConfigurationFingerprint: strOrNull(
        policies.provider_configuration_fingerprint,
        'policies.provider_configuration_fingerprint',
      ),
    },
    usage: {
      estimatedCostUsd: numOrNull(usage.estimated_cost_usd, 'usage.estimated_cost_usd'),
      actualCostUsd: numOrNull(usage.actual_cost_usd, 'usage.actual_cost_usd'),
      costUnknown: bool(usage.cost_unknown, 'usage.cost_unknown'),
      unknownCostRecordCount: num(usage.unknown_cost_record_count, 'usage.unknown_cost_record_count'),
      inputTokens: numOrNull(usage.input_tokens, 'usage.input_tokens'),
      outputTokens: numOrNull(usage.output_tokens, 'usage.output_tokens'),
      calls: list(usage.calls, 'usage.calls').map((rawCall, index) => {
        const call = record(rawCall, `usage.calls[${index}]`)
        return {
          ordinal: numOrNull(call.ordinal, `usage.calls[${index}].ordinal`),
          dimensionId: strOrNull(call.dimension_id, `usage.calls[${index}].dimension_id`),
          provider: str(call.provider, `usage.calls[${index}].provider`),
          model: str(call.model, `usage.calls[${index}].model`),
          elapsedMs: numOrNull(call.elapsed_ms, `usage.calls[${index}].elapsed_ms`),
          usageKind: str(call.usage_kind, `usage.calls[${index}].usage_kind`),
          inputTokens: numOrNull(call.input_tokens, `usage.calls[${index}].input_tokens`),
          outputTokens: numOrNull(call.output_tokens, `usage.calls[${index}].output_tokens`),
          costUsd: numOrNull(call.cost_usd, `usage.calls[${index}].cost_usd`),
          costUnknown: bool(call.cost_unknown, `usage.calls[${index}].cost_unknown`),
        }
      }),
    },
    providerHealth: {
      profileName: str(health.profile_name, 'provider_health.profile_name'),
      status: oneOf(
        health.status,
        ['healthy', 'last_call_failed', 'not_tested'] as const,
        'provider_health.status',
      ),
      observedAt: strOrNull(health.observed_at, 'provider_health.observed_at'),
    },
    availableActions: {
      retry: mapActionCapability(actions.retry, 'available_actions.retry'),
      bypass: mapActionCapability(actions.bypass, 'available_actions.bypass'),
      openCheck: mapActionCapability(actions.open_check, 'available_actions.open_check'),
      openSessionInsight: mapActionCapability(
        actions.open_session_insight,
        'available_actions.open_session_insight',
      ),
    },
    // Absent on fixture/mock runs; present when the live API provides it.
    ...(typeof dto.session_insight_deep_link === 'string'
      ? { sessionInsightDeepLink: dto.session_insight_deep_link }
      : {}),
  }
}

export function mapOverviewDto(raw: unknown): OverviewView {
  const dto = record(raw, 'overview') as unknown as OverviewDto
  const stats = record(dto.stats, 'overview.stats')
  const sessionInsight = record(dto.session_insight, 'overview.session_insight')

  return {
    attention: list(dto.attention, 'overview.attention').map((summary, index) =>
      mapReviewSummaryDto(summary, `attention[${index}]`),
    ),
    active: list(dto.active, 'overview.active').map((summary, index) =>
      mapReviewSummaryDto(summary, `active[${index}]`),
    ),
    recent: list(dto.recent, 'overview.recent').map((summary, index) =>
      mapReviewSummaryDto(summary, `recent[${index}]`),
    ),
    stats: {
      attemptCount: num(stats.attempt_count, 'stats.attempt_count'),
      passedCount: num(stats.passed_count, 'stats.passed_count'),
      blockedCount: num(stats.blocked_count, 'stats.blocked_count'),
      errorCount: num(stats.error_count, 'stats.error_count'),
      gatePassRate: numOrNull(stats.gate_pass_rate, 'stats.gate_pass_rate'),
      errorRate: numOrNull(stats.error_rate, 'stats.error_rate'),
      averageDurationMs: numOrNull(stats.average_duration_ms, 'stats.average_duration_ms'),
      knownCostUsd: num(stats.known_cost_usd, 'stats.known_cost_usd'),
      unknownCostRecordCount: num(stats.unknown_cost_record_count, 'stats.unknown_cost_record_count'),
      knownInputTokens: num(stats.known_input_tokens, 'stats.known_input_tokens'),
      knownOutputTokens: num(stats.known_output_tokens, 'stats.known_output_tokens'),
    } satisfies OverviewStatsView,
    gateTrend: list(dto.gate_trend, 'overview.gate_trend').map((rawPoint, index) => {
      const point = record(rawPoint, `gate_trend[${index}]`)
      return {
        date: str(point.date, `gate_trend[${index}].date`),
        passed: num(point.passed, `gate_trend[${index}].passed`),
        blocked: num(point.blocked, `gate_trend[${index}].blocked`),
        error: num(point.error, `gate_trend[${index}].error`),
        inProgress: num(point.in_progress, `gate_trend[${index}].in_progress`),
      }
    }),
    findingSeverity: list(dto.finding_severity, 'overview.finding_severity').map(
      (rawCount, index) => {
        const count = record(rawCount, `finding_severity[${index}]`)
        return {
          severity: oneOf(count.severity, SEVERITIES, `finding_severity[${index}].severity`),
          count: num(count.count, `finding_severity[${index}].count`),
        }
      },
    ),
    dimensionHealth: list(dto.dimension_health, 'overview.dimension_health').map(
      (rawDimension, index) => {
        const dimension = record(rawDimension, `dimension_health[${index}]`)
        return {
          dimensionId: str(dimension.dimension_id, `dimension_health[${index}].dimension_id`),
          completedCount: num(dimension.completed_count, `dimension_health[${index}].completed_count`),
          failedCount: num(dimension.failed_count, `dimension_health[${index}].failed_count`),
          averageElapsedMs: numOrNull(
            dimension.average_elapsed_ms,
            `dimension_health[${index}].average_elapsed_ms`,
          ),
        }
      },
    ),
    policyUsage: list(dto.policy_usage, 'overview.policy_usage').map((rawPolicy, index) => {
      const policy = record(rawPolicy, `policy_usage[${index}]`)
      return {
        reviewPolicyVersion: str(
          policy.review_policy_version,
          `policy_usage[${index}].review_policy_version`,
        ),
        reviewCount: num(policy.review_count, `policy_usage[${index}].review_count`),
        blockedCount: num(policy.blocked_count, `policy_usage[${index}].blocked_count`),
        errorCount: num(policy.error_count, `policy_usage[${index}].error_count`),
      }
    }),
    providerHealth: list(dto.provider_health, 'overview.provider_health').map(
      (rawHealth, index) => {
        const health = record(rawHealth, `provider_health[${index}]`)
        return {
          profileName: str(health.profile_name, `provider_health[${index}].profile_name`),
          status: oneOf(
            health.status,
            ['healthy', 'last_call_failed', 'not_tested'] as const,
            `provider_health[${index}].status`,
          ),
          observedAt: strOrNull(health.observed_at, `provider_health[${index}].observed_at`),
        }
      },
    ),
    sessionInsight: {
      state: oneOf(sessionInsight.state, SESSION_INSIGHT_STATES, 'session_insight.state'),
      currentAttemptId: strOrNull(sessionInsight.current_attempt_id, 'session_insight.current_attempt_id'),
      childSessionCount: num(sessionInsight.child_session_count, 'session_insight.child_session_count'),
      lastProbeAt: strOrNull(sessionInsight.last_probe_at, 'session_insight.last_probe_at'),
    },
  }
}
