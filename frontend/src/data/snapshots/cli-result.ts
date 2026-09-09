export interface CliPolicyVersion {
  semver: string
  sha256: string
}

export interface CliResultDocument {
  schema: 'worktree-review.cli.result/v1'
  gate_state: string
  attempt_id: string
  source_repository: string
  target_ref: string
  target_head_oid: string
  proposed_ref: string
  proposed_source: string
  proposed_head_oid: string
  merge_tree_oid: string | null
  review_identity: { merge_tree_oid: string; review_policy_version: CliPolicyVersion } | null
  review_policy_version: CliPolicyVersion
  compute_policy_version: CliPolicyVersion
  compute_policy_disclosure: {
    provider: string
    model: string
    data_destination: string
    known_retention: string
    provider_configuration_fingerprint: string | null
  }
  stage_outcomes: Array<{ stage: string; status: string; detail: string | null }>
  dimension_outcomes: Array<{ dimension_id: string; status: string; detail: string | null }>
  findings: Array<{
    fingerprint: string
    severity: string
    evidence_band: string
    problem_statement: string
    expected_impact: string
    repair_guidance: string | null
    dimension_id: string
    evidence_spans: Array<{
      path: string
      start_line: number
      end_line: number
      quoted_text: string
      source: string
      snapshot_identity: string | null
      change_kind: string | null
    }>
  }>
  coverage: {
    required_coverage_complete: boolean
    mandatory_missing: string[]
    optional_missing: string[]
    excluded: string[]
    unreviewable: string[]
    reviewed: string[]
  }
  usage: Array<{
    kind: string
    input_tokens: number | null
    output_tokens: number | null
    cost_usd: string | null
    provider: string
    model: string
    note: string | null
  }>
  summary: string
  error_detail: string | null
}

export interface PipelineSnapshotFile {
  metadata: {
    caseKey: string
    provenance: 'pipeline-snapshot'
    badge: string
    generatedAt: string
    resultSchema: string
    reviewPolicy: CliPolicyVersion
    computePolicy: CliPolicyVersion
    provider: string
    model: string
    providerConfigurationFingerprint: string | null
    dataDestination: string
    knownRetention: string
  }
  result: CliResultDocument
}
