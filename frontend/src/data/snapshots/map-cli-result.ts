import { localActions } from '../fixtures/shared.ts'
import type {
  CoverageFileView,
  EvidenceBand,
  FindingSeverity,
  GateState,
  PipelineStageName,
  PipelineStageStatus,
  PipelineStageView,
  ReviewFindingView,
  ReviewRunView,
  RunStatus,
} from '../../domain/review.ts'
import { PIPELINE_STAGE_ORDER } from '../../domain/review.ts'
import type { CliResultDocument, PipelineSnapshotFile } from './cli-result.ts'

const GATE_STATES: Record<string, GateState> = {
  'Awaiting review': 'awaiting_review',
  'In progress': 'in_progress',
  Passed: 'passed',
  'Passed with bypass': 'passed_with_bypass',
  Blocked: 'blocked',
  Error: 'error',
}

function mapGate(value: string): GateState {
  const mapped = GATE_STATES[value]
  if (!mapped) {
    throw new Error(`Unknown CLI gate_state: ${value}`)
  }
  return mapped
}

function mapRunStatus(gate: GateState): RunStatus {
  return gate === 'error' ? 'failed' : 'completed'
}

function mapStageStatus(value: string): PipelineStageStatus {
  if (value === 'completed' || value === 'failed' || value === 'not-started') {
    return value
  }
  throw new Error(`Unknown CLI stage status: ${value}`)
}

function mapSeverity(value: string): FindingSeverity {
  if (value === 'critical' || value === 'major' || value === 'minor' || value === 'suggestion') {
    return value
  }
  throw new Error(`Unknown CLI severity: ${value}`)
}

function mapEvidenceBand(value: string): EvidenceBand {
  if (value === 'insufficient') {
    return 'insufficient'
  }
  return 'supported'
}

function coverageFiles(result: CliResultDocument): CoverageFileView[] {
  const files: CoverageFileView[] = []
  for (const path of result.coverage.reviewed) {
    files.push({ path, category: 'reviewed', reason: null, rule: null })
  }
  for (const path of result.coverage.mandatory_missing) {
    files.push({
      path,
      category: 'mandatory-missing',
      reason: 'Mandatory path was not reviewed.',
      rule: 'mandatory-glob',
    })
  }
  for (const path of result.coverage.optional_missing) {
    files.push({
      path,
      category: 'optional-missing',
      reason: 'Optional path was not present in this result.',
      rule: 'optional-glob',
    })
  }
  for (const path of result.coverage.excluded) {
    files.push({ path, category: 'excluded', reason: 'Excluded by Review Policy.', rule: 'excluded-glob' })
  }
  for (const path of result.coverage.unreviewable) {
    files.push({
      path,
      category: 'unreviewable',
      reason: result.error_detail ?? 'Content could not be reviewed.',
      rule: 'unreviewable',
    })
  }
  return files
}

function pipeline(result: CliResultDocument): PipelineStageView[] {
  const byName = new Map(result.stage_outcomes.map((outcome) => [outcome.stage, outcome]))
  return PIPELINE_STAGE_ORDER.map((stage: PipelineStageName) => {
    const outcome = byName.get(stage)
    return {
      stage,
      status: outcome ? mapStageStatus(outcome.status) : 'not-started',
      elapsedMs: null,
      safeError: outcome?.detail ?? null,
    }
  })
}

function findings(result: CliResultDocument): ReviewFindingView[] {
  return result.findings.map((finding) => ({
    fingerprint: finding.fingerprint,
    severity: mapSeverity(finding.severity),
    evidenceBand: mapEvidenceBand(finding.evidence_band),
    dimensionId: finding.dimension_id,
    problemStatement: finding.problem_statement,
    expectedImpact: finding.expected_impact,
    repairGuidance: finding.repair_guidance ?? 'Not reported',
    blocking: finding.severity === 'critical' || finding.severity === 'major',
    evidenceSpans: finding.evidence_spans.map((span) => ({
      path: span.path,
      startLine: span.start_line,
      endLine: span.end_line,
      source: span.source,
      snapshotIdentity: span.snapshot_identity ?? 'not-reported',
      changeKind: span.change_kind ?? 'not-reported',
      quotedText: span.quoted_text,
    })),
  }))
}

export const PIPELINE_SNAPSHOT_BADGE = 'Pipeline snapshot · local'

export function mapPipelineSnapshot(file: PipelineSnapshotFile): ReviewRunView {
  const result = file.result
  const gateState = mapGate(result.gate_state)
  const runStatus = mapRunStatus(gateState)
  const sourceKind =
    result.proposed_source === 'current-worktree-snapshot' ? 'local-worktree' : 'local-committed-ref'
  const costUnknown = result.usage.every((record) => record.cost_usd === null)
  const knownCosts = result.usage
    .map((record) => (record.cost_usd === null ? null : Number(record.cost_usd)))
    .filter((value): value is number => value !== null && !Number.isNaN(value))
  const source = {
    kind: sourceKind,
    repositoryDisplayName: result.source_repository,
    worktreeLabel: sourceKind === 'local-worktree' ? 'WORKTREE' : null,
    targetRef: result.target_ref,
    proposedRef: result.proposed_ref,
    snapshotSha: result.proposed_head_oid,
  } as const
  const failedStage = result.stage_outcomes.find((outcome) => outcome.status === 'failed')

  return {
    attemptId: result.attempt_id,
    runStatus,
    gateState,
    authority: 'local_non_authoritative',
    publicationStatus: 'not_applicable',
    bypassState: 'none',
    source,
    summary: {
      attemptId: result.attempt_id,
      repositoryDisplayName: result.source_repository,
      source,
      runStatus,
      gateState,
      authority: 'local_non_authoritative',
      publicationStatus: 'not_applicable',
      bypassState: 'none',
      findingCount: result.findings.length,
      highestSeverity: findings(result)[0]?.severity ?? null,
      durationMs: null,
      costUsd: knownCosts.length === 0 ? null : knownCosts.reduce((sum, value) => sum + value, 0),
      costUnknown,
      provider: result.compute_policy_disclosure.provider,
      model: result.compute_policy_disclosure.model,
      createdAt: file.metadata.generatedAt,
      completedAt: file.metadata.generatedAt,
    },
    gate: {
      gateState,
      blockingFingerprints: findings(result)
        .filter((finding) => finding.blocking)
        .map((finding) => finding.fingerprint),
      summary: result.summary,
      requiredCoverageComplete: result.coverage.required_coverage_complete,
    },
    findings: findings(result),
    coverage: {
      requiredCoverage: result.coverage.required_coverage_complete ? 'complete' : 'incomplete',
      reviewedCount: result.coverage.reviewed.length,
      excludedCount: result.coverage.excluded.length,
      missingCount: result.coverage.mandatory_missing.length,
      files: coverageFiles(result),
    },
    dimensions: result.dimension_outcomes.map((outcome) => ({
      dimensionId: outcome.dimension_id,
      status:
        outcome.status === 'completed' || outcome.status === 'failed' || outcome.status === 'not-started'
          ? outcome.status
          : 'not-started',
      elapsedMs: null,
      findingCount: findings(result).filter((finding) => finding.dimensionId === outcome.dimension_id).length,
      blockingFindingCount: findings(result).filter(
        (finding) => finding.dimensionId === outcome.dimension_id && finding.blocking,
      ).length,
    })),
    pipeline: pipeline(result),
    failure:
      failedStage === undefined
        ? null
        : {
            stage: failedStage.stage as PipelineStageName,
            category: 'pipeline',
            safeDetail: result.error_detail ?? failedStage.detail ?? 'Pipeline stage failed.',
          },
    attempts: [
      {
        attemptId: result.attempt_id,
        authority: 'local_non_authoritative',
        gateState,
        trigger: 'local-pipeline-snapshot',
        provider: result.compute_policy_disclosure.provider,
        model: result.compute_policy_disclosure.model,
        reviewPolicyVersion: result.review_policy_version.semver,
        computePolicyVersion: result.compute_policy_version.semver,
        tokenCount: null,
        costUsd: knownCosts.length === 0 ? null : knownCosts.reduce((sum, value) => sum + value, 0),
        costUnknown,
        startedAt: file.metadata.generatedAt,
        durationMs: null,
      },
    ],
    identity: {
      reviewRequestKey: `${result.source_repository}:${result.target_ref}:${result.proposed_ref}`,
      sourceRepository: result.source_repository,
      targetRef: result.target_ref,
      targetHeadOid: result.target_head_oid,
      proposedSource: result.proposed_ref,
      proposedHeadOid: result.proposed_head_oid,
      mergeTreeOid: result.merge_tree_oid,
      reviewIdentity: result.review_identity?.merge_tree_oid ?? null,
      identityUnavailableReason:
        result.review_identity === null
          ? 'Review identity unavailable — merge candidate was not constructed.'
          : null,
    },
    policies: {
      reviewPolicyName: 'demo-review-policy',
      reviewPolicyVersion: result.review_policy_version.semver,
      reviewPolicySha256: result.review_policy_version.sha256,
      computePolicyName: 'demo-local-cli',
      computePolicyVersion: result.compute_policy_version.semver,
      computePolicySha256: result.compute_policy_version.sha256,
      dataDestination: result.compute_policy_disclosure.data_destination,
      retentionDisclosure: result.compute_policy_disclosure.known_retention,
      providerConfigurationFingerprint:
        result.compute_policy_disclosure.provider_configuration_fingerprint,
    },
    usage: {
      estimatedCostUsd: null,
      actualCostUsd: knownCosts.length === 0 ? null : knownCosts.reduce((sum, value) => sum + value, 0),
      costUnknown,
      unknownCostRecordCount: result.usage.filter((record) => record.cost_usd === null).length,
      inputTokens: result.usage.reduce((sum, record) => sum + (record.input_tokens ?? 0), 0),
      outputTokens: result.usage.reduce((sum, record) => sum + (record.output_tokens ?? 0), 0),
      calls: result.usage.map((record, index) => ({
        ordinal: index + 1,
        dimensionId: null,
        provider: record.provider,
        model: record.model,
        elapsedMs: null,
        usageKind: record.kind,
        inputTokens: record.input_tokens,
        outputTokens: record.output_tokens,
        costUsd: record.cost_usd === null ? null : Number(record.cost_usd),
        costUnknown: record.cost_usd === null,
      })),
    },
    providerHealth: {
      profileName: result.compute_policy_disclosure.provider,
      status: 'not_tested',
      observedAt: file.metadata.generatedAt,
    },
    availableActions: localActions(),
  }
}
