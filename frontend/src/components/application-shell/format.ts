import type { ProviderHealthView } from '../../domain/review.ts'

export function formatProviderFreshness(health: ProviderHealthView | undefined): string {
  if (!health) {
    return 'Provider not tested'
  }
  if (health.status === 'not_tested' || !health.observedAt) {
    return `${health.profileName}: not tested`
  }
  if (health.status === 'last_call_failed') {
    return `${health.profileName}: last call failed at ${formatUtc(health.observedAt)}`
  }
  return `${health.profileName}: healthy at ${formatUtc(health.observedAt)}`
}

export function formatUtc(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}
