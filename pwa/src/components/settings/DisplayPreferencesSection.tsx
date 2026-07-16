'use client'

import { t } from '@/lib/i18n'
import { useDisplayPreferences } from '@/hooks/useDisplayPreferences'
import {
  persistUiPreferences,
  saveLocalDisplayPreferences,
  type GridDensityPreference,
} from '@/lib/uiPreferences'

const DENSITIES: GridDensityPreference[] = ['spacious', 'comfortable', 'compact']
const FONT_SCALES = [0.875, 1, 1.125, 1.25]

export function DisplayPreferencesSection() {
  const preferences = useDisplayPreferences()

  function update(patch: Parameters<typeof saveLocalDisplayPreferences>[0]) {
    saveLocalDisplayPreferences(patch)
    void persistUiPreferences(patch)
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      <div className="px-5 py-4 space-y-5">
        <h2 className="font-medium text-vault-text text-sm">{t('settings.displayDensity')}</h2>

        <div className="space-y-2">
          <p className="text-xs text-vault-text-muted">{t('settings.gridDensityDesc')}</p>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label={t('settings.gridDensity')}>
            {DENSITIES.map((density) => (
              <button
                key={density}
                type="button"
                role="radio"
                aria-checked={preferences.gallery_grid_density === density}
                onClick={() => update({ gallery_grid_density: density })}
                className={`rounded-lg border px-3 py-2 text-xs transition-colors ${
                  preferences.gallery_grid_density === density
                    ? 'border-vault-accent text-vault-accent bg-vault-accent/10'
                    : 'border-vault-border text-vault-text-secondary hover:border-vault-border-hover'
                }`}
              >
                {t(`settings.gridDensity.${density}`)}
              </button>
            ))}
          </div>
        </div>

        <label className="block space-y-2">
          <span className="text-xs font-medium text-vault-text-secondary">{t('settings.gridColumns')}</span>
          <select
            value={preferences.gallery_grid_columns}
            onChange={(event) => update({ gallery_grid_columns: Number(event.target.value) })}
            className="w-full bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-sm text-vault-text"
          >
            <option value={0}>{t('settings.gridColumnsAuto')}</option>
            {[4, 5, 6, 7, 8, 9, 10, 11, 12].map((count) => (
              <option key={count} value={count}>
                {t('settings.gridColumnsCount', { count: String(count) })}
              </option>
            ))}
          </select>
          <span className="block text-xs text-vault-text-muted">{t('settings.gridColumnsDesc')}</span>
        </label>

        <div className="space-y-2">
          <p className="text-xs font-medium text-vault-text-secondary">{t('settings.fontScale')}</p>
          <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label={t('settings.fontScale')}>
            {FONT_SCALES.map((scale) => (
              <button
                key={scale}
                type="button"
                role="radio"
                aria-checked={preferences.font_scale === scale}
                onClick={() => update({ font_scale: scale })}
                className={`rounded-lg border px-2 py-2 text-xs transition-colors ${
                  preferences.font_scale === scale
                    ? 'border-vault-accent text-vault-accent bg-vault-accent/10'
                    : 'border-vault-border text-vault-text-secondary hover:border-vault-border-hover'
                }`}
              >
                {Math.round(scale * 100)}%
              </button>
            ))}
          </div>
          <p className="text-xs text-vault-text-muted">{t('settings.fontScaleDesc')}</p>
        </div>
      </div>
    </div>
  )
}
