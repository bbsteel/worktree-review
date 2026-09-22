import { Link } from 'react-router'
import { useI18n } from '../../i18n.tsx'
import type { ConfigSetupItem, ConfigSetupItemId } from './config-readiness.ts'

const ITEM_LABEL: Record<ConfigSetupItemId, string> = {
  repository: 'Register a repository',
  'review-policy': 'Review Policy ready (built-in or registered)',
  'compute-policy': 'Compute Policy bound to a configured Provider',
}

const ITEM_FIX: Record<ConfigSetupItemId, string> = {
  repository: 'Open Repositories',
  'review-policy': 'Open Policies',
  'compute-policy': 'Open Compute Policies',
}

/**
 * Shared setup checklist for Overview (when incomplete) and New Review
 * hard-block. Items link to the pages that fix them.
 */
export function ConfigSetupChecklist({
  items,
  title,
  description,
}: {
  items: ConfigSetupItem[]
  title: string
  description?: string
}) {
  const { t } = useI18n()
  const incomplete = items.filter((item) => !item.ready)
  if (incomplete.length === 0) {
    return null
  }

  return (
    <section
      aria-label={title}
      className="rounded-lg border border-status-warning bg-surface p-4"
    >
      <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      {description !== undefined ? (
        <p className="mt-1 text-meta text-text-secondary">{description}</p>
      ) : null}
      <ul className="mt-3 flex flex-col gap-2">
        {incomplete.map((item) => (
          <li
            key={item.id}
            className="flex flex-wrap items-center justify-between gap-2 text-sm text-text-primary"
          >
            <span>{t(ITEM_LABEL[item.id])}</span>
            <Link
              to={item.href}
              className="text-sm text-action-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            >
              {t(ITEM_FIX[item.id])}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
