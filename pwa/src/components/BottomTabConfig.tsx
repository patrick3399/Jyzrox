'use client'

import { useState, useCallback } from 'react'
import { Check, GripVertical } from 'lucide-react'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { ALL_TABS, BOTTOM_TAB_CONFIG_KEY, TAB_COUNT, DEFAULT_TAB_HREFS, loadTabConfig, type TabDefinition } from '@/components/BottomTabBar'

function loadSelectedHrefs(): string[] {
  return loadTabConfig().map((tab) => tab.href)
}

function saveSelectedHrefs(hrefs: string[]) {
  localStorage.setItem(BOTTOM_TAB_CONFIG_KEY, JSON.stringify(hrefs))
  // Notify other tabs / BottomTabBar instances
  window.dispatchEvent(
    new StorageEvent('storage', { key: BOTTOM_TAB_CONFIG_KEY, newValue: JSON.stringify(hrefs) }),
  )
}

export function BottomTabConfig() {
  useLocale()
  const [selected, setSelected] = useState<string[]>(() => loadSelectedHrefs())
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  const toggleTab = useCallback(
    (href: string) => {
      setSelected((prev) => {
        let next: string[]
        if (prev.includes(href)) {
          // Deselect only if more than 1 selected (must keep at least 1 to allow reordering)
          if (prev.length <= 1) return prev
          next = prev.filter((h) => h !== href)
        } else {
          if (prev.length >= TAB_COUNT) {
            // Replace the last item
            next = [...prev.slice(0, TAB_COUNT - 1), href]
          } else {
            next = [...prev, href]
          }
        }
        if (next.length === TAB_COUNT) saveSelectedHrefs(next)
        return next
      })
    },
    [],
  )

  const handleReset = useCallback(() => {
    setSelected(DEFAULT_TAB_HREFS)
    saveSelectedHrefs(DEFAULT_TAB_HREFS)
  }, [])

  // Drag-and-drop reordering among selected tabs
  const handleDragStart = useCallback((idx: number) => {
    setDragIdx(idx)
  }, [])

  const handleDragEnter = useCallback((idx: number) => {
    setDragOver(idx)
  }, [])

  const handleDragEnd = useCallback(() => {
    if (dragIdx !== null && dragOver !== null && dragIdx !== dragOver) {
      setSelected((prev) => {
        const next = [...prev]
        const [moved] = next.splice(dragIdx, 1)
        next.splice(dragOver, 0, moved)
        if (next.length === TAB_COUNT) saveSelectedHrefs(next)
        return next
      })
    }
    setDragIdx(null)
    setDragOver(null)
  }, [dragIdx, dragOver])

  const selectedCount = selected.length

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">{t('settings.bottomTabDesc')}</p>

      {/* Current order preview */}
      {selectedCount > 0 && (
        <div className="mb-4">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('settings.bottomTabSelect')} ({selectedCount}/{TAB_COUNT})
          </p>
          <div className="flex gap-1.5 flex-wrap">
            {selected.map((href, idx) => {
              const tab = ALL_TABS.find((t) => t.href === href)
              if (!tab) return null
              const Icon = tab.icon
              const isDragging = dragIdx === idx
              const isOver = dragOver === idx
              return (
                <div
                  key={href}
                  draggable
                  onDragStart={() => handleDragStart(idx)}
                  onDragEnter={() => handleDragEnter(idx)}
                  onDragEnd={handleDragEnd}
                  onDragOver={(e) => e.preventDefault()}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium cursor-grab select-none transition-all ${
                    isDragging
                      ? 'opacity-40 border-vault-accent bg-vault-accent/10 text-vault-accent'
                      : isOver
                      ? 'border-vault-accent bg-vault-accent/15 text-vault-accent scale-105'
                      : 'border-vault-border bg-vault-input text-vault-text-secondary'
                  }`}
                >
                  <GripVertical size={12} className="text-vault-text-muted shrink-0" />
                  <Icon size={14} />
                  <span>{t(tab.labelKey)}</span>
                  <span className="text-vault-text-muted text-[10px]">{idx + 1}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* All available tabs */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {ALL_TABS.map((tab) => {
          const isSelected = selected.includes(tab.href)
          const position = selected.indexOf(tab.href)
          const Icon = tab.icon
          const isDisabled = !isSelected && selectedCount >= TAB_COUNT
          return (
            <button
              key={tab.href}
              onClick={() => toggleTab(tab.href)}
              disabled={isDisabled}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-sm text-left transition-colors ${
                isSelected
                  ? 'border-vault-accent bg-vault-accent/10 text-vault-accent'
                  : isDisabled
                  ? 'border-vault-border bg-vault-input text-vault-text-muted opacity-40 cursor-not-allowed'
                  : 'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'
              }`}
            >
              <Icon size={16} className="shrink-0" />
              <span className="flex-1 truncate">{t(tab.labelKey)}</span>
              {isSelected && (
                <span className="flex items-center justify-center w-4 h-4 rounded-full bg-vault-accent text-white text-[9px] font-bold shrink-0">
                  {position + 1}
                </span>
              )}
              {!isSelected && !isDisabled && (
                <Check size={14} className="text-vault-text-muted/40 shrink-0" />
              )}
            </button>
          )
        })}
      </div>

      {/* Reset */}
      <div className="mt-4 flex justify-end">
        <button
          onClick={handleReset}
          className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors underline underline-offset-2"
        >
          {t('settings.bottomTabReset')}
        </button>
      </div>
    </div>
  )
}
