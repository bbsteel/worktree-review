import type { ProviderHealthView } from '../../domain/review.ts'

type Translator = (key: string, variables?: Record<string, string | number>) => string

export function formatProviderFreshness(
  health: ProviderHealthView | undefined,
  translate: Translator = (key) => key,
): string {
  if (!health) {
    return translate('Provider not tested')
  }
  if (health.status === 'not_tested' || !health.observedAt) {
    return translate('{profile}: not tested', { profile: health.profileName })
  }
  if (health.status === 'last_call_failed') {
    return translate('{profile}: last call failed at {timestamp}', {
      profile: health.profileName,
      timestamp: formatUtc(health.observedAt),
    })
  }
  return translate('{profile}: healthy at {timestamp}', {
    profile: health.profileName,
    timestamp: formatUtc(health.observedAt),
  })
}

export function formatUtc(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}
