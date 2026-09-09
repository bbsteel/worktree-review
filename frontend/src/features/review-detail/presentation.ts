/**
 * Deterministic presentation projection for Review Detail (design W14).
 * Every status pairs an icon, text and color token; color is never the only signal.
 */
import type { BadgeTone } from '../../components/ui/badge.tsx'
import type {
  Authority,
  BypassState,
  CoverageCategory,
  EvidenceBand,
  FindingSeverity,
  GateState,
  PipelineStageName,
  PipelineStageStatus,
  PublicationStatus,
  ReviewSourceKind,
  RunStatus,
} from '../../domain/review.ts'

export interface StatusPresentation {
  tone: BadgeTone
  label: string
  description: string
}

export const GATE_PRESENTATION: Record<GateState, StatusPresentation> = {
  awaiting_review: {
    tone: 'awaiting',
    label: 'Awaiting Review',
    description: 'The attempt is queued and review has not started.',
  },
  in_progress: {
    tone: 'running',
    label: 'In Progress',
    description: 'The review pipeline is currently executing.',
  },
  passed: {
    tone: 'passed',
    label: 'Passed',
    description: 'Review completed and the merge candidate is allowed to pass.',
  },
  passed_with_bypass: {
    tone: 'passed-with-bypass',
    label: 'Passed with Bypass',
    description: 'Blocking findings were accepted by authorization. This is not a clean pass.',
  },
  blocked: {
    tone: 'blocked',
    label: 'Blocked',
    description: 'Review completed and found blocking risks in the code.',
  },
  error: {
    tone: 'error',
    label: 'Error',
    description: 'The review did not finish; the outcome for the code is unknown.',
  },
}

export const RUN_STATUS_PRESENTATION: Record<RunStatus, StatusPresentation> = {
  queued: { tone: 'awaiting', label: 'Queued', description: 'Waiting for a worker.' },
  preparing: { tone: 'running', label: 'Preparing', description: 'Inputs are being resolved.' },
  running: { tone: 'running', label: 'Running', description: 'The pipeline is executing.' },
  completed: { tone: 'passed', label: 'Completed', description: 'Execution finished.' },
  failed: { tone: 'error', label: 'Failed', description: 'Execution failed before completion.' },
  interrupted: {
    tone: 'error',
    label: 'Interrupted',
    description: 'The service restarted while this attempt was running; it was not resumed.',
  },
}

export const SEVERITY_PRESENTATION: Record<FindingSeverity, StatusPresentation> = {
  critical: { tone: 'critical', label: 'Critical', description: 'Highest risk; usually blocking.' },
  major: { tone: 'major', label: 'Major', description: 'Major problem; blocking by default policy.' },
  minor: { tone: 'minor', label: 'Minor', description: 'Needs attention but not blocking by default.' },
  suggestion: { tone: 'suggestion', label: 'Suggestion', description: 'Improvement suggestion.' },
}

export const EVIDENCE_BAND_PRESENTATION: Record<EvidenceBand, { label: string; description: string }> = {
  supported: {
    label: 'Supported',
    description: 'Verified against quoted evidence tied to an immutable snapshot.',
  },
  insufficient: {
    label: 'Insufficient',
    description: 'Evidence is incomplete; treat the conclusion with care.',
  },
}

export const AUTHORITY_PRESENTATION: Record<Authority, StatusPresentation> = {
  local_non_authoritative: {
    tone: 'neutral',
    label: 'Local one-shot result',
    description: 'A one-time local result. It does not change any GitHub standing decision.',
  },
  authoritative: {
    tone: 'neutral',
    label: 'Authoritative attempt',
    description: 'The current attempt that governs the standing decision.',
  },
  superseded: {
    tone: 'awaiting',
    label: 'Superseded',
    description: 'A newer attempt replaced this one. It can no longer publish or change the standing decision.',
  },
  audit_only: {
    tone: 'neutral',
    label: 'Audit only',
    description: 'Retained for audit. It cannot publish or change the standing decision.',
  },
}

export const PUBLICATION_PRESENTATION: Record<PublicationStatus, { label: string }> = {
  not_applicable: { label: 'Not applicable' },
  queued: { label: 'Check publication queued' },
  in_progress: { label: 'Check publication in progress' },
  published: { label: 'Check published' },
  failed: { label: 'Check publication failed' },
}

export const BYPASS_PRESENTATION: Record<Exclude<BypassState, 'none'>, StatusPresentation> = {
  active: {
    tone: 'passed-with-bypass',
    label: 'Bypass active',
    description: 'Risk accepted by authorization. The findings were not resolved.',
  },
  invalidated: {
    tone: 'warning',
    label: 'Bypass invalidated',
    description: 'A previous risk acceptance no longer applies to the current review identity.',
  },
}

export const SOURCE_KIND_LABEL: Record<ReviewSourceKind, string> = {
  'local-worktree': 'Current worktree',
  'local-recent-commits': 'Recent commits + worktree',
  'local-committed-ref': 'Committed ref',
  'github-pull-request': 'GitHub pull request',
}

export const COVERAGE_CATEGORY_PRESENTATION: Record<CoverageCategory, { label: string; description: string }> = {
  reviewed: { label: 'Reviewed', description: 'Content reviewed by the pipeline.' },
  'mandatory-missing': {
    label: 'Mandatory missing',
    description: 'Required by policy but not reviewed. This makes coverage incomplete.',
  },
  'optional-missing': { label: 'Optional missing', description: 'Optional context that was not available.' },
  excluded: { label: 'Excluded', description: 'Excluded by Review Policy rules.' },
  unreviewable: { label: 'Unreviewable', description: 'Changed content could not be reviewed.' },
}

export const PIPELINE_STAGE_LABEL: Record<PipelineStageName, string> = {
  'derive-identity': 'Derive Identity',
  'construct-merge': 'Construct Merge',
  'prepare-review-worktree': 'Prepare Review Worktree',
  'gather-context': 'Gather Context',
  'run-dimensions': 'Run Dimensions',
  'verify-dedup': 'Verify & Deduplicate',
  'check-completeness': 'Check Completeness',
  'evaluate-gate': 'Evaluate Gate',
  publish: 'Publish',
}

export const STAGE_STATUS_PRESENTATION: Record<PipelineStageStatus, { label: string }> = {
  'not-started': { label: 'Not started' },
  running: { label: 'Running' },
  completed: { label: 'Completed' },
  failed: { label: 'Failed' },
}
