'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { Menu } from 'lucide-react'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useState, useEffect, useRef, useCallback } from 'react'
import { PAGE_REGISTRY, type PageDef } from '@/lib/pageRegistry'
import { getTabHref, clearTabMemory, markTabRestore } from '@/lib/navMemory'

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

export function getDefaultTabs(): TabDefinition[] {
  return DEFAULT_TAB_HREFS.map((href) => ALL_TABS.find((t) => t.href === href)!)
}

interface BottomTabBarProps {
  onMoreClick: () => void
  downloadStats?: { running: number; finished: number }
}

export function BottomTabBar({ onMoreClick, downloadStats: stats }: BottomTabBarProps) {
  useLocale()
  const pathname = usePathname()
  const router = useRouter()
  const [tabs, setTabs] = useState<TabDefinition[]>(getDefaultTabs)
  // Resolved hrefs (last visited URL per tab) — computed after mount to avoid a
  // hydration mismatch; first render falls back to the bare tab href.
  const [resolvedHrefs, setResolvedHrefs] = useState<Record<string, string>>({})
  const lastTapRef = useRef<{ root: string; time: number }>({ root: '', time: 0 })

  useEffect(() => {
    setTabs(loadTabConfig())
  }, [])

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const tab of tabs) next[tab.href] = getTabHref(tab.href)
    setResolvedHrefs(next)
  }, [tabs, pathname])

  const handleTabClick = useCallback(
    (e: React.MouseEvent, root: string) => {
      const isActive = pathname === root || (root !== '/' && pathname.startsWith(root))
      if (!isActive) {
        // Restoring a deep sub-page from another section: flag it so the back
        // button there climbs to the section list instead of history-backing
        // into the section we're leaving now.
        const target = resolvedHrefs[root] ?? root
        if (target.split('?')[0] !== root) markTabRestore(target)
        return // let <Link> navigate to the remembered href
      }
      e.preventDefault()
      const now = Date.now()
      const last = lastTapRef.current
      if (last.root === root && now - last.time < 400) {
        // double tap → reset this tab
        lastTapRef.current = { root: '', time: 0 }
        clearTabMemory(root)
        router.push(root)
      } else {
        lastTapRef.current = { root, time: now }
        window.scrollTo({ top: 0 })
      }
    },
    [pathname, router, resolvedHrefs],
  )

  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === BOTTOM_TAB_CONFIG_KEY) {
        setTabs(loadTabConfig())
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  return (
    <nav
      className="app-touch-controls lg:hidden fixed bottom-0 left-0 right-0 z-50 bg-vault-card border-t border-vault-border flex"
      style={{ paddingBottom: 'var(--sab)', height: 'calc(4rem + var(--sab))' }}
      onContextMenu={(event) => event.preventDefault()}
    >
      {tabs.map(({ href, labelKey, icon: Icon }) => {
        const isActive = pathname === href || (href !== '/' && pathname.startsWith(href))
        return (
          <Link
            key={href}
            href={resolvedHrefs[href] ?? href}
            onClick={(e) => handleTabClick(e, href)}
            className={`flex flex-col items-center justify-center flex-1 gap-1 text-xs transition-colors relative ${
              isActive ? 'text-vault-accent' : 'text-vault-text-secondary hover:text-vault-text'
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
