export const FIXTURE_CASE_KEYS = ['passed', 'blocked', 'error_merge_conflict'] as const

export type FixtureCaseKey = (typeof FIXTURE_CASE_KEYS)[number]

export const BLOCKED_DEMO_ATTEMPT_ID = 'attempt_01JY8R7F2W'
export const PASSED_DEMO_ATTEMPT_ID = 'attempt_01JY8P4SS0D'
export const ERROR_DEMO_ATTEMPT_ID = 'attempt_01JY8E4R0R'

export const MOCK_DATA_BADGE = 'Mock data · Pre-Alpha'

/** Frozen clock for deterministic duration and cost. Not Date.now(). */
export const FIXTURE_CLOCK = '2026-09-09T16:00:00.000Z'

export const BLOCKED_DURATION_MS = 138_000
export const BLOCKED_COST_USD = 0.42
export const PASSED_DURATION_MS = 131_000
export const PASSED_COST_USD = 0.18
export const ERROR_DURATION_MS = 4_200

export const LONG_EVIDENCE_PATH =
  'src/platform/webhooks/authorization/fallback/legacy/compat/v2/internal/handlers/unsigned_requests/verify_signature_or_accept.py'

export const LONG_HASH = '3f8c1d92e4b70aa18c6d5e4f0b91c27d8e4a1b2c9f0e7d6a5b4c3d2e1f0a9b8c'

export const MERGE_CONFLICT_ERROR = [
  'Merge candidate was not constructed: git merge --no-commit --no-ff failed with conflicts.',
  'Conflicting paths include:',
  'src/webhooks/verify.py',
  'src/webhooks/authorization/legacy_unsigned_fallback.py',
  'src/config/provider.py',
  'src/server/app.py',
  LONG_EVIDENCE_PATH,
  'packages/internal/billing/adapters/stripe/webhooks/signature.py',
  'Conflict markers remain in the index; Review Identity cannot be derived from a missing merge tree.',
].join(' ')
