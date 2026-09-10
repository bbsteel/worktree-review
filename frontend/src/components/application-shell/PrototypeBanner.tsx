import { useNavigate } from 'react-router'
import { useDataSource } from '../../app/data-source.ts'
import { useI18n } from '../../i18n.tsx'

export function PrototypeBanner() {
  const { source, cases } = useDataSource()
  const { t } = useI18n()
  const navigate = useNavigate()
  const badge = source.environmentBadge

  if (!badge) {
    return null
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 border-b border-status-warning/40 bg-surface-subtle px-4 py-2 text-sm text-text-primary"
    >
      <span className="font-medium" data-testid="prototype-badge">
        {badge}
      </span>
      <span className="text-text-secondary">
        {t('Prototype environment. Demo cases only — no live Provider, GitHub, or Session Insight.')}
      </span>
      <label className="ml-auto flex items-center gap-2 text-xs text-text-secondary">
        {t('Demo case')}
        <select
          aria-label={t('Demo case')}
          className="min-h-10 rounded-md border border-border bg-background px-2 text-sm text-text-primary"
          defaultValue=""
          onChange={(event) => {
            const attemptId = event.target.value
            if (attemptId) {
              navigate(`/reviews/${attemptId}`)
            }
          }}
        >
          <option value="">{t('Select a case')}</option>
          {cases.map((item) => (
            <option key={`${item.provenance}:${item.attemptId}`} value={item.attemptId}>
              {item.provenance === 'pipeline-snapshot' ? `${t('Pipeline snapshot')} · ` : `${t('Mock data')} · `}
              {item.title}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
