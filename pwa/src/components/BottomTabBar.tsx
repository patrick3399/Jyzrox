'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Menu } from 'lucide-react'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useState, useEffect } from 'react'
import { PAGE_REGISTRY, type PageDef } from '@/lib/pageRegistry'

// Re-export for BottomTabConfig compatibility
export type TabDefinition = PageDef

export const ALL_TABS: TabDefinition[] = PAGE_REGISTRY.filter((p) => p.nav)

export const DEFAULT_TAB_HREFS = ['/e-hentai', '/pixiv', '/library', '/queue']
export const BOTTOM_TAB_CONFIG_KEY = 'bottom_tab_config'
export const TAB_COUNT = 4

export function loadTabConfig(): TabDefinition[] {
  if (typeof window === 'undefined') return getDefaultTabs()
  try {
    const raw = localStorage.getItem(BOTTOM_TAB_CONFIG_KEY)
    if (!raw) return getDefaultTabs()
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length !== TAB_COUNT) return getDefaultTabs()
    const resolved: TabDefinition[] = []
    for (const href of parsed) {
      if (typeof href !== 'string') return getDefaultTabs()
      const found = ALL_TABS.find((tab) => tab.href === href)
      if (!found) return getDefaultTabs()
      resolved.push(found)
    }
    return resolved
  } catch {
    return getDefaultTabs()
  }
}

function getDefaultTabs(): TabDefinition[] {
  return DEFAULT_TAB_HREFS.map((href) => ALL_TABS.find((t) => t.href === href)!)
}

interface BottomTabBarProps {
  onMoreClick: () => void
}

export function BottomTabBar({ onMoreClick }: BottomTabBarProps) {
  useLocale()
  const pathname = usePathname()
  const { data: stats } = useDownloadStats()
  const [tabs, setTabs] = useState<TabDefinition[]>(loadTabConfig)

  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === BOTTOM_TAB_CONFIG_KEY) {
        setTabs(loadTabConfig())
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  if (pathname.startsWith('/reader/')) return null

  return (
    <nav
      className="lg:hidden fixed bottom-0 left-0 right-0 z-50 bg-vault-card border-t border-vault-border flex"
      style={{ paddingBottom: 'var(--sab)', height: 'calc(4rem + var(--sab))' }}
    >
      {tabs.map(({ href, labelKey, icon: Icon }) => {
        const isActive = pathname === href || (href !== '/' && pathname.startsWith(href))
        return (
          <Link
            key={href}
            href={href}
            className={`flex flex-col items-center justify-center flex-1 gap-1 text-xs transition-colors relative ${
              isActive
                ? 'text-vault-accent'
                : 'text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            <span className="relative">
              <Icon size={22} />
              {href === '/queue' && stats && (
                <>
                  {stats.running > 0 && (
                    <span className="absolute -top-1.5 -right-2 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-blue-500 text-white text-[9px] font-bold px-1 leading-none">
                      {stats.running}
                    </span>
                  )}
                  {stats.running === 0 && stats.finished > 0 && (
                    <span className="absolute -top-1.5 -right-2 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-green-500 text-white text-[9px] font-bold px-1 leading-none">
                      {stats.finished}
                    </span>
                  )}
                </>
              )}
            </span>
            <span>{t(labelKey)}</span>
          </Link>
        )
      })}

      {/* More button */}
      <button
        onClick={onMoreClick}
        className="flex flex-col items-center justify-center flex-1 gap-1 text-xs transition-colors text-vault-text-secondary hover:text-vault-text"
        aria-label={t('nav.more')}
      >
        <Menu size={22} />
        <span>{t('nav.more')}</span>
      </button>
    </nav>
  )
}
