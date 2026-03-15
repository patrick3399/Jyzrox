'use client'

import { useState, useCallback } from 'react'
import { Check, GripVertical } from 'lucide-react'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PAGE_REGISTRY, type PageDef } from '@/lib/pageRegistry'

const ALL_DASHBOARD_LINKS: PageDef[] = PAGE_REGISTRY.filter((p) => p.dashboard)

export const DASHBOARD_LINKS_CONFIG_KEY = 'dashboard_quick_links'

export const DEFAULT_DASHBOARD_HREFS: string[] = [
  '/e-hentai', '/pixiv', '/library', '/explorer', '/artists', '/images',
]

export function loadDashboardConfig(): PageDef[] {
  if (typeof window === 'undefined') return ALL_DASHBOARD_LINKS
  try {
    const raw = localStorage.getItem(DASHBOARD_LINKS_CONFIG_KEY)
    if (!raw) return ALL_DASHBOARD_LINKS
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length === 0) return ALL_DASHBOARD_LINKS
    const resolved: PageDef[] = []
    for (const href of parsed) {
      if (typeof href !== 'string') return ALL_DASHBOARD_LINKS
      const found = ALL_DASHBOARD_LINKS.find((p) => p.href === href)
      // Skip unknown hrefs silently (pages removed from registry)
      if (found) resolved.push(found)
    }
    if (resolved.length === 0) return ALL_DASHBOARD_LINKS
    return resolved
  } catch {
    return ALL_DASHBOARD_LINKS
  }
}

function saveSelectedHrefs(hrefs: string[]) {
  localStorage.setItem(DASHBOARD_LINKS_CONFIG_KEY, JSON.stringify(hrefs))
  // Notify other tabs / Dashboard instances
  window.dispatchEvent(
    new StorageEvent('storage', { key: DASHBOARD_LINKS_CONFIG_KEY, newValue: JSON.stringify(hrefs) }),
  )
}

function loadSelectedHrefs(): string[] {
  return loadDashboardConfig().map((p) => p.href)
}

export function DashboardLinksConfig() {
  useLocale()
  const [selected, setSelected] = useState<string[]>(() => loadSelectedHrefs())
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  const toggleLink = useCallback((href: string) => {
    setSelected((prev) => {
      let next: string[]
      if (prev.includes(href)) {
        // Must keep at least 1 selected
        if (prev.length <= 1) return prev
        next = prev.filter((h) => h !== href)
      } else {
        next = [...prev, href]
      }
      saveSelectedHrefs(next)
      return next
    })
  }, [])

  const handleReset = useCallback(() => {
    setSelected(DEFAULT_DASHBOARD_HREFS)
    saveSelectedHrefs(DEFAULT_DASHBOARD_HREFS)
  }, [])

  // Drag-and-drop reordering among selected links
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
        saveSelectedHrefs(next)
        return next
      })
    }
    setDragIdx(null)
    setDragOver(null)
  }, [dragIdx, dragOver])

  const selectedCount = selected.length

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">{t('settings.dashboardLinksDesc')}</p>

      {/* Current order preview */}
      {selectedCount > 0 && (
        <div className="mb-4">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('settings.dashboardLinksSelect')} ({selectedCount})
          </p>
          <div className="flex gap-1.5 flex-wrap">
            {selected.map((href, idx) => {
              const page = ALL_DASHBOARD_LINKS.find((p) => p.href === href)
              if (!page) return null
              const Icon = page.icon
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
                  <span>{t(page.labelKey)}</span>
                  <span className="text-vault-text-muted text-[10px]">{idx + 1}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* All available links */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {ALL_DASHBOARD_LINKS.map((page) => {
          const isSelected = selected.includes(page.href)
          const position = selected.indexOf(page.href)
          const Icon = page.icon
          return (
            <button
              key={page.href}
              onClick={() => toggleLink(page.href)}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-sm text-left transition-colors ${
                isSelected
                  ? 'border-vault-accent bg-vault-accent/10 text-vault-accent'
                  : 'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'
              }`}
            >
              <Icon size={16} className="shrink-0" />
              <span className="flex-1 truncate">{t(page.labelKey)}</span>
              {isSelected && (
                <span className="flex items-center justify-center w-4 h-4 rounded-full bg-vault-accent text-white text-[9px] font-bold shrink-0">
                  {position + 1}
                </span>
              )}
              {!isSelected && (
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
          {t('settings.dashboardLinksReset')}
        </button>
      </div>
    </div>
  )
}
