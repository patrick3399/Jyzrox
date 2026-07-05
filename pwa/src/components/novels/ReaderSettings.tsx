'use client'

import { Minus, Plus } from 'lucide-react'
import { t } from '@/lib/i18n'

export type ReaderTheme = 'light' | 'dark' | 'sepia'

export interface ReaderPrefs {
  fontSize: number
  theme: ReaderTheme
}

export const DEFAULT_READER_PREFS: ReaderPrefs = { fontSize: 18, theme: 'dark' }

const THEMES: { key: ReaderTheme; labelKey: string }[] = [
  { key: 'light', labelKey: 'novels.themeLight' },
  { key: 'dark', labelKey: 'novels.themeDark' },
  { key: 'sepia', labelKey: 'novels.themeSepia' },
]

export function ReaderSettings({
  prefs,
  onChange,
}: {
  prefs: ReaderPrefs
  onChange: (next: ReaderPrefs) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-2" aria-label={t('novels.fontSize')}>
        <span className="text-xs text-vault-text-muted">{t('novels.fontSize')}</span>
        <button
          type="button"
          aria-label={`${t('novels.fontSize')} -`}
          className="rounded border border-vault-border p-1 hover:border-vault-accent"
          onClick={() => onChange({ ...prefs, fontSize: Math.max(12, prefs.fontSize - 1) })}
        >
          <Minus className="size-3" />
        </button>
        <span className="w-6 text-center text-sm text-vault-text" data-testid="reader-font-size">
          {prefs.fontSize}
        </span>
        <button
          type="button"
          aria-label={`${t('novels.fontSize')} +`}
          className="rounded border border-vault-border p-1 hover:border-vault-accent"
          onClick={() => onChange({ ...prefs, fontSize: Math.min(32, prefs.fontSize + 1) })}
        >
          <Plus className="size-3" />
        </button>
      </div>

      <div className="flex items-center gap-1" role="group" aria-label={t('novels.theme')}>
        {THEMES.map((th) => (
          <button
            key={th.key}
            type="button"
            aria-pressed={prefs.theme === th.key}
            className={`rounded border px-2 py-1 text-xs ${
              prefs.theme === th.key
                ? 'border-vault-accent text-vault-text'
                : 'border-vault-border text-vault-text-muted'
            }`}
            onClick={() => onChange({ ...prefs, theme: th.key })}
          >
            {t(th.labelKey)}
          </button>
        ))}
      </div>
    </div>
  )
}
