'use client'

import { useEffect, useState } from 'react'
import { useTheme } from 'next-themes'
import { AlertTriangle, Check, Monitor, RotateCcw } from 'lucide-react'
import { t } from '@/lib/i18n'
import {
  ACCENT_PRESETS,
  DEFAULT_ACCENT,
  DEFAULT_CUSTOM_PALETTE,
  contrastRatio,
  loadAccent,
  loadCustomPalette,
  saveAccent,
  saveCustomPalette,
  type CustomPalette,
} from '@/lib/themeOverrides'
import { persistUiPreferences, type ThemePreference } from '@/lib/uiPreferences'

const PRESET_SWATCHES: Record<string, { bg: string; card: string; text: string }> = {
  light: { bg: '#ffffff', card: '#f5f5f5', text: '#171717' },
  dark: { bg: '#0a0a0a', card: '#141414', text: '#e5e5e5' },
  amoled: { bg: '#000000', card: '#0a0a0a', text: '#e5e5e5' },
}

const THEME_ORDER = ['light', 'dark', 'amoled', 'custom', 'system'] as const

function themeLabel(value: string): string {
  switch (value) {
    case 'light':
      return t('common.light')
    case 'dark':
      return t('common.dark')
    case 'amoled':
      return t('common.amoled')
    case 'custom':
      return t('settings.themeCustom')
    default:
      return t('common.system')
  }
}

function SwatchPreview({ palette, accent }: { palette: CustomPalette; accent: string }) {
  return (
    <span
      className="flex h-6 w-10 overflow-hidden rounded border border-vault-border"
      style={{ backgroundColor: palette.bg }}
      aria-hidden
    >
      <span className="m-auto flex gap-0.5">
        <span className="h-3 w-2 rounded-sm" style={{ backgroundColor: palette.card }} />
        <span className="h-3 w-2 rounded-sm" style={{ backgroundColor: palette.text }} />
        <span className="h-3 w-2 rounded-sm" style={{ backgroundColor: accent }} />
      </span>
    </span>
  )
}

export function ThemeSection() {
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const [accent, setAccent] = useState<string | null>(null)
  const [palette, setPalette] = useState<CustomPalette>(DEFAULT_CUSTOM_PALETTE)

  useEffect(() => {
    setMounted(true)
    setAccent(loadAccent())
    setPalette(loadCustomPalette())
  }, [])

  if (!mounted) return null

  const effectiveAccent = accent ?? DEFAULT_ACCENT
  const accentLowContrast = contrastRatio('#ffffff', effectiveAccent) < 3
  const textLowContrast = theme === 'custom' && contrastRatio(palette.text, palette.bg) < 4.5

  function pickAccent(value: string | null) {
    setAccent(value)
    saveAccent(value)
    void persistUiPreferences({ accent: value })
  }

  function updatePalette(patch: Partial<CustomPalette>) {
    const next = { ...palette, ...patch }
    setPalette(next)
    saveCustomPalette(next)
    void persistUiPreferences({ custom_palette: next })
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      <div className="px-5 py-4 space-y-4">
        <h2 className="font-medium text-vault-text text-sm">{t('settings.themeSection')}</h2>

        {/* Theme choice */}
        <div role="radiogroup" aria-label={t('settings.themeSection')} className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {THEME_ORDER.map((value) => {
            const selected = theme === value
            const swatch = value === 'custom' ? palette : PRESET_SWATCHES[value]
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => {
                  setTheme(value)
                  void persistUiPreferences({ theme: value as ThemePreference })
                }}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                  selected
                    ? 'border-vault-accent text-vault-text'
                    : 'border-vault-border text-vault-text-secondary hover:border-vault-border-hover'
                }`}
              >
                {swatch ? (
                  <SwatchPreview palette={swatch} accent={effectiveAccent} />
                ) : (
                  <Monitor className="h-5 w-5 text-vault-text-muted" aria-hidden />
                )}
                <span className="flex-1 text-left">{themeLabel(value)}</span>
                {selected && <Check className="h-4 w-4 text-vault-accent" aria-hidden />}
              </button>
            )
          })}
        </div>

        {/* Accent color */}
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-vault-text-secondary">{t('settings.accentColor')}</h3>
          <div className="flex flex-wrap items-center gap-2">
            {ACCENT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                aria-label={preset}
                aria-pressed={effectiveAccent === preset}
                onClick={() => pickAccent(preset === DEFAULT_ACCENT ? null : preset)}
                className={`flex h-7 w-7 items-center justify-center rounded-full border-2 ${
                  effectiveAccent === preset ? 'border-vault-text' : 'border-transparent'
                }`}
                style={{ backgroundColor: preset }}
              >
                {effectiveAccent === preset && <Check className="h-4 w-4 text-white" aria-hidden />}
              </button>
            ))}
            <input
              type="color"
              aria-label={t('settings.accentPickCustom')}
              value={effectiveAccent}
              onChange={(e) => pickAccent(e.target.value)}
              className="h-7 w-9 cursor-pointer rounded border border-vault-border bg-transparent p-0.5"
            />
            {accent != null && (
              <button
                type="button"
                onClick={() => pickAccent(null)}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-vault-text-secondary hover:text-vault-text"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                {t('settings.accentReset')}
              </button>
            )}
          </div>
          {accentLowContrast && (
            <p className="flex items-center gap-1.5 text-xs text-amber-500">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {t('settings.contrastWarningAccent')}
            </p>
          )}
        </div>

        {/* Custom palette editor */}
        {theme === 'custom' && (
          <div className="space-y-2">
            <h3 className="text-xs font-medium text-vault-text-secondary">{t('settings.customThemeColors')}</h3>
            <div className="flex flex-wrap gap-4">
              {(
                [
                  ['bg', t('settings.customThemeBg')],
                  ['card', t('settings.customThemeCard')],
                  ['text', t('settings.customThemeText')],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 text-sm text-vault-text">
                  <input
                    type="color"
                    aria-label={label}
                    value={palette[key]}
                    onChange={(e) => updatePalette({ [key]: e.target.value })}
                    className="h-7 w-9 cursor-pointer rounded border border-vault-border bg-transparent p-0.5"
                  />
                  {label}
                </label>
              ))}
              <button
                type="button"
                onClick={() => {
                  setPalette(DEFAULT_CUSTOM_PALETTE)
                  saveCustomPalette(DEFAULT_CUSTOM_PALETTE)
                  void persistUiPreferences({ custom_palette: DEFAULT_CUSTOM_PALETTE })
                }}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-vault-text-secondary hover:text-vault-text"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                {t('settings.customThemeReset')}
              </button>
            </div>
            <p className="text-xs text-vault-text-muted">{t('settings.customThemeHint')}</p>
            {textLowContrast && (
              <p className="flex items-center gap-1.5 text-xs text-amber-500">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                {t('settings.contrastWarningText')}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
