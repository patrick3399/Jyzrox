'use client'

import { Popover } from '@/components/ui/popover'
import { t } from '@/lib/i18n'
import type { GridDensityPreference } from '@/lib/uiPreferences'

export const DENSITY_OPTIONS: GridDensityPreference[] = ['spacious', 'comfortable', 'compact']

interface LibraryViewMenuProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  anchor: Element | null
  showLayout: boolean
  showDensity: boolean
  viewMode: 'grid' | 'list'
  onViewModeChange: (mode: 'grid' | 'list') => void
  density: GridDensityPreference
  densityOverridden: boolean
  onDensityChange: (density: GridDensityPreference) => void
  onFollowSettings: () => void
}

const OPTION =
  'flex-1 rounded-md border px-3 py-2 text-xs transition-colors whitespace-nowrap'
const OPTION_ACTIVE = 'border-vault-accent bg-vault-accent/10 text-vault-accent'
const OPTION_IDLE =
  'border-vault-border text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'

/** Layout and density options for the Library search bar; loaded on first open. */
export function LibraryViewMenu({
  open,
  onOpenChange,
  anchor,
  showLayout,
  showDensity,
  viewMode,
  onViewModeChange,
  density,
  densityOverridden,
  onDensityChange,
  onFollowSettings,
}: LibraryViewMenuProps) {
  return (
    <Popover
      open={open}
      onOpenChange={onOpenChange}
      anchor={anchor}
      align="end"
      ariaLabel={t('library.viewOptions')}
      className="w-64 p-3 space-y-3"
    >
      {showLayout && (
        <div className="flex gap-2" role="radiogroup" aria-label={t('library.viewOptions')}>
          {(['grid', 'list'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={viewMode === mode}
              onClick={() => onViewModeChange(mode)}
              className={`${OPTION} ${viewMode === mode ? OPTION_ACTIVE : OPTION_IDLE}`}
            >
              {mode === 'grid' ? t('browse.gridView') : t('browse.listView')}
            </button>
          ))}
        </div>
      )}
      {showDensity && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-vault-text-secondary">{t('library.density')}</p>
          <div className="flex gap-2" role="radiogroup" aria-label={t('library.density')}>
            {DENSITY_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={density === option}
                onClick={() => onDensityChange(option)}
                className={`${OPTION} ${density === option ? OPTION_ACTIVE : OPTION_IDLE}`}
              >
                {t(`settings.gridDensity.${option}`)}
              </button>
            ))}
          </div>
          {densityOverridden && (
            <button
              type="button"
              onClick={onFollowSettings}
              className="text-xs text-vault-accent hover:underline"
            >
              {t('library.densityFollowSettings')}
            </button>
          )}
        </div>
      )}
    </Popover>
  )
}
