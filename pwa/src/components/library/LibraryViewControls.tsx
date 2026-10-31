'use client'

import { useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { Grid3x3, LayoutGrid, List } from 'lucide-react'
import { useOpenedOnce } from '@/hooks/useOpenedOnce'
import { t } from '@/lib/i18n'
import type { GridDensityPreference } from '@/lib/uiPreferences'

// Base UI Popover stays out of the page's initial JS until the menu first opens.
const LibraryViewMenu = dynamic(
  () => import('@/components/library/LibraryViewMenu').then((module) => module.LibraryViewMenu),
  { ssr: false },
)

interface LibraryViewControlsProps {
  viewMode: 'grid' | 'list'
  onViewModeChange: (mode: 'grid' | 'list') => void
  /** Density currently in effect (override, else Settings). */
  density: GridDensityPreference
  densityOverridden: boolean
  onDensityChange: (density: GridDensityPreference) => void
  onFollowSettings: () => void
  /** Reports the menu's open state so the search block keeps itself revealed. */
  onMenuOpenChange?: (open: boolean) => void
}

const BUTTON = 'relative h-10 w-10 items-center justify-center rounded-lg border transition-colors'
const ACTIVE = 'border-vault-accent bg-vault-accent/10 text-vault-accent'
const IDLE =
  'border-vault-border bg-vault-input text-vault-text-secondary hover:text-vault-text hover:border-vault-border-hover'

// The search block locks its reveal while it holds focus, so a tap must not leave focus on a button.
const preventFocus = (e: React.MouseEvent) => e.preventDefault()

type MenuKind = 'view' | 'density'

/**
 * Grid/list and density controls for the Library search bar. Below `sm` a single
 * View button opens a menu with both; from `sm` the layout toggle is inline and
 * only density opens a menu. Density does not apply to the list layout.
 */
export function LibraryViewControls({
  viewMode,
  onViewModeChange,
  density,
  densityOverridden,
  onDensityChange,
  onFollowSettings,
  onMenuOpenChange,
}: LibraryViewControlsProps) {
  const [open, setOpenState] = useState(false)
  const [menu, setMenu] = useState<{ anchor: HTMLElement; kind: MenuKind } | null>(null)
  const menuOpened = useOpenedOnce(open)
  // Open state at pointer-down, before outside-press dismissal can close the
  // menu: the anchor is not a Base UI Trigger, so it counts as "outside" and a
  // second tap would otherwise close on press and reopen on click.
  const openAtPointerDownRef = useRef<boolean | null>(null)

  const setOpen = (next: boolean) => {
    setOpenState(next)
    onMenuOpenChange?.(next)
  }

  const toggleFrom = (kind: MenuKind, anchor: HTMLElement) => {
    const wasOpen = openAtPointerDownRef.current ?? open
    openAtPointerDownRef.current = null
    setMenu({ anchor, kind })
    setOpen(!wasOpen)
  }

  const handlePointerDown = () => {
    openAtPointerDownRef.current = open
  }

  const isList = viewMode === 'list'

  return (
    <>
      <button
        type="button"
        data-testid="library-view-menu-button"
        onMouseDown={preventFocus}
        onPointerDownCapture={handlePointerDown}
        onClick={(e) => toggleFrom('view', e.currentTarget)}
        aria-haspopup="dialog"
        aria-expanded={open && menu?.kind === 'view'}
        aria-label={t('library.viewOptions')}
        title={t('library.viewOptions')}
        className={`${BUTTON} flex sm:hidden ${open && menu?.kind === 'view' ? ACTIVE : IDLE}`}
      >
        {isList ? <List size={16} /> : <LayoutGrid size={16} />}
      </button>

      <div
        data-testid="library-view-inline"
        role="radiogroup"
        aria-label={t('library.viewOptions')}
        className="hidden sm:flex h-10 shrink-0 overflow-hidden rounded-lg border border-vault-border"
      >
        {(['grid', 'list'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={viewMode === mode}
            onMouseDown={preventFocus}
            onClick={() => onViewModeChange(mode)}
            aria-label={mode === 'grid' ? t('browse.gridView') : t('browse.listView')}
            title={mode === 'grid' ? t('browse.gridView') : t('browse.listView')}
            className={`flex w-9 items-center justify-center transition-colors ${
              viewMode === mode
                ? 'bg-vault-input text-vault-text'
                : 'text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {mode === 'grid' ? <LayoutGrid size={15} /> : <List size={15} />}
          </button>
        ))}
      </div>

      {!isList && (
        <button
          type="button"
          data-testid="library-density-button"
          onMouseDown={preventFocus}
          onPointerDownCapture={handlePointerDown}
          onClick={(e) => toggleFrom('density', e.currentTarget)}
          aria-haspopup="dialog"
          aria-expanded={open && menu?.kind === 'density'}
          aria-label={t('library.density')}
          title={t('library.density')}
          className={`${BUTTON} hidden sm:flex ${open && menu?.kind === 'density' ? ACTIVE : IDLE}`}
        >
          <Grid3x3 size={16} />
        </button>
      )}

      {menuOpened && (
        <LibraryViewMenu
          open={open}
          onOpenChange={setOpen}
          anchor={menu?.anchor ?? null}
          showLayout={menu?.kind === 'view'}
          showDensity={!isList}
          viewMode={viewMode}
          onViewModeChange={onViewModeChange}
          density={density}
          densityOverridden={densityOverridden}
          onDensityChange={onDensityChange}
          onFollowSettings={onFollowSettings}
        />
      )}
    </>
  )
}
