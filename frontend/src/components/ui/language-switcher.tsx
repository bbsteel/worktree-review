import { useI18n, type Locale } from '../../i18n.tsx'

const locales: Array<{ value: Locale; labelKey: string }> = [
  { value: 'en', labelKey: 'English' },
  { value: 'zh-CN', labelKey: 'Simplified Chinese' },
]

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n()

  return (
    <label className="flex min-h-10 items-center gap-2 text-sm text-text-secondary">
      <span className="sr-only">{t('Language')}</span>
      <select
        aria-label={t('Language')}
        className="min-h-10 rounded-md border border-border bg-background px-2 text-sm text-text-primary"
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {locales.map((option) => (
          <option key={option.value} value={option.value}>
            {t(option.labelKey)}
          </option>
        ))}
      </select>
    </label>
  )
}
