'use client'

import { useState, useCallback, useMemo } from 'react'
import { Check, GripVertical } from 'lucide-react'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PAGE_REGISTRY, hasRole, type PageDef } from '@/lib/pageRegistry'
import { useDragReorder } from '@/hooks/useDragReorder'

export const SIDEBAR_CONFIG_KEY = 'sidebar_nav_order'

interface SidebarNavConfig {
  order: string[]
  hidden: string[]
}

function getDefaultOrder(): string[] {
  return PAGE_REGISTRY.filter((p) => p.sidebar).map((p) => p.href)
}

export function loadSidebarConfig(): SidebarNavConfig {
  if (typeof window === 'undefined') {
    return { order: getDefaultOrder(), hidden: [] }
  }
  try {
    const raw = localStorage.getItem(SIDEBAR_CONFIG_KEY)
    if (!raw) return { order: getDefaultOrder(), hidden: [] }
    const parsed: unknown = JSON.parse(raw)
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      !Array.isArray((parsed as SidebarNavConfig).order) ||
      !Array.isArray((parsed as SidebarNavConfig).hidden)
    ) {
      return { order: getDefaultOrder(), hidden: [] }
    }
    const config = parsed as SidebarNavConfig
    // Validate — filter out hrefs no longer in registry
    const allSidebarHrefs = new Set(PAGE_REGISTRY.filter((p) => p.sidebar).map((p) => p.href))
    const validOrder = config.order.filter((h) => typeof h === 'string' && allSidebarHrefs.has(h))
    const validHidden = config.hidden.filter((h) => typeof h === 'string' && allSidebarHrefs.has(h))
    // Auto-append new registry pages not in either list
    const knownHrefs = new Set([...validOrder, ...validHidden])
    for (const href of allSidebarHrefs) {
      if (!knownHrefs.has(href)) {
        validOrder.push(href)
      }
    }
    if (validOrder.length === 0 && validHidden.length === 0) {
      return { order: getDefaultOrder(), hidden: [] }
    }
    return { order: validOrder, hidden: validHidden }
  } catch {
    return { order: getDefaultOrder(), hidden: [] }
  }
}

export function saveSidebarConfig(config: SidebarNavConfig): void {
  const json = JSON.stringify(config)
  localStorage.setItem(SIDEBAR_CONFIG_KEY, json)
  window.dispatchEvent(new StorageEvent('storage', { key: SIDEBAR_CONFIG_KEY, newValue: json }))
}

interface SidebarConfigProps {
  userRole?: string
}

export function SidebarConfig({ userRole }: SidebarConfigProps) {
  useLocale()
  const [config, setConfig] = useState<SidebarNavConfig>(() => loadSidebarConfig())

  const handleReorder = useCallback((newOrder: string[]) => {
    setConfig((prev) => {
      const next = { ...prev, order: newOrder }
      saveSidebarConfig(next)
      return next
    })
  }, [])

  const { dragIdx, dragOver, getDragProps } = useDragReorder({
    items: config.order,
    onReorder: handleReorder,
  })

  const toggleHref = useCallback((href: string) => {
    setConfig((prev) => {
      let next: SidebarNavConfig
      if (prev.hidden.includes(href)) {
        // Un-hide: move back into order at the end
        next = {
          order: [...prev.order, href],
          hidden: prev.hidden.filter((h) => h !== href),
        }
      } else {
        // Hide: must keep at least 1 visible
        if (prev.order.length <= 1) return prev
        next = {
          order: prev.order.filter((h) => h !== href),
          hidden: [...prev.hidden, href],
        }
      }
      saveSidebarConfig(next)
      return next
    })
  }, [])

  const handleReset = useCallback(() => {
    const next: SidebarNavConfig = { order: getDefaultOrder(), hidden: [] }
    setConfig(next)
    saveSidebarConfig(next)
  }, [])

  // All sidebar pages visible to this user
  const allAvailable = useMemo<PageDef[]>(
    () => PAGE_REGISTRY.filter((p) => p.sidebar && hasRole(userRole, p.minRole ?? 'viewer')),
    [userRole],
  )

  const orderCount = config.order.length

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">{t('settings.sidebarOrderDesc')}</p>

      {/* Current order (draggable chips) */}
      {orderCount > 0 && (
        <div className="mb-4">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('settings.sidebarOrderSelect')} ({orderCount})
          </p>
          <div className="flex gap-1.5 flex-wrap">
            {config.order.map((href, idx) => {
              const page = allAvailable.find((p) => p.href === href)
              if (!page) return null
              const Icon = page.icon
              const isDragging = dragIdx === idx
              const isOver = dragOver === idx
              return (
                <div
                  key={href}
                  {...getDragProps(idx)}
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

      {/* Toggle grid — all available pages */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {allAvailable.map((page) => {
          const isVisible = config.order.includes(page.href)
          const position = config.order.indexOf(page.href)
          const Icon = page.icon
          return (
            <button
              key={page.href}
              onClick={() => toggleHref(page.href)}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-sm text-left transition-colors ${
                isVisible
                  ? 'border-vault-accent bg-vault-accent/10 text-vault-accent'
                  : 'border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text'
              }`}
            >
              <Icon size={16} className="shrink-0" />
              <span className="flex-1 truncate">{t(page.labelKey)}</span>
              {isVisible && (
                <span className="flex items-center justify-center w-4 h-4 rounded-full bg-vault-accent text-white text-[9px] font-bold shrink-0">
                  {position + 1}
                </span>
              )}
              {!isVisible && <Check size={14} className="text-vault-text-muted/40 shrink-0" />}
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
          {t('settings.sidebarOrderReset')}
        </button>
      </div>
    </div>
  )
}
