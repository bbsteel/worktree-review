import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nProvider, messages, useI18n } from './i18n.tsx'

function TranslationProbe() {
  const { locale, t } = useI18n()
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <h1>{t('Overview')}</h1>
      <p>{t('Needs attention · {count}', { count: 3 })}</p>
    </div>
  )
}

describe('i18n', () => {
  it('renders Simplified Chinese translations and interpolates values', () => {
    render(
      <I18nProvider initialLocale="zh-CN">
        <TranslationProbe />
      </I18nProvider>,
    )

    expect(screen.getByTestId('locale')).toHaveTextContent('zh-CN')
    expect(screen.getByRole('heading', { name: '概览' })).toBeVisible()
    expect(screen.getByText('需要关注 · 3')).toBeVisible()
  })

  it('keeps English as the source locale', () => {
    render(
      <I18nProvider initialLocale="en">
        <TranslationProbe />
      </I18nProvider>,
    )

    expect(screen.getByRole('heading', { name: 'Overview' })).toBeVisible()
    expect(screen.getByText('Needs attention · 3')).toBeVisible()
  })

  it('keeps every source message available in Simplified Chinese', () => {
    for (const key of Object.keys(messages.en)) {
      expect(messages['zh-CN'][key], `missing zh-CN message: ${key}`).toBeDefined()
    }
  })
})
