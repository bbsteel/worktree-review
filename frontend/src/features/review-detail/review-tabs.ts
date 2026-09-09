/**
 * Review Detail tab identifiers and URL state helpers (design 13.1).
 * The active tab survives refresh and direct links via ?tab=;
 * Finding selection and filters use additional query params.
 */
export const REVIEW_DETAIL_TABS = [
  'overview',
  'findings',
  'coverage',
  'attempts',
  'identity',
  'policies',
  'usage',
] as const

export type ReviewDetailTabId = (typeof REVIEW_DETAIL_TABS)[number]

export const REVIEW_DETAIL_TAB_LABEL: Record<ReviewDetailTabId, string> = {
  overview: 'Overview',
  findings: 'Findings',
  coverage: 'Coverage',
  attempts: 'Attempts',
  identity: 'Identity & Provenance',
  policies: 'Policies',
  usage: 'Usage',
}

export function isReviewDetailTabId(value: string | null): value is ReviewDetailTabId {
  return value !== null && (REVIEW_DETAIL_TABS as readonly string[]).includes(value)
}

export function readTabParam(searchParams: URLSearchParams): ReviewDetailTabId {
  const tab = searchParams.get('tab')
  return isReviewDetailTabId(tab) ? tab : 'overview'
}

/** Replace the tab param while preserving finding selection and filters. */
export function withTabParam(searchParams: URLSearchParams, tab: ReviewDetailTabId): URLSearchParams {
  const next = new URLSearchParams(searchParams)
  if (tab === 'overview') {
    next.delete('tab')
  } else {
    next.set('tab', tab)
  }
  return next
}
