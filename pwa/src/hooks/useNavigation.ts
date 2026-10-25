import { useState, useEffect, useMemo, useCallback, type MouseEvent } from 'react'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import useSWR from 'swr'
import { Sun, Moon, MoonStar, Monitor, Palette } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'
import { useLocale } from '@/components/LocaleProvider'
import { PAGE_REGISTRY, hasRole, passesFeatureFlag, type PageDef } from '@/lib/pageRegistry'
import { getListHref, getTabHref, markTabRestore } from '@/lib/navMemory'
import {
  getDefaultSidebarConfig,
  loadSidebarConfig,
  SIDEBAR_CONFIG_KEY,
} from '@/components/SidebarConfig'

const THEME_CYCLE = ['light', 'dark', 'amoled', 'system'] as const

const THEME_ICON: Record<string, typeof Sun> = {
  light: Sun,
  dark: Moon,
  amoled: MoonStar,
  custom: Palette,
  system: Monitor,
}

const THEME_LABEL: Record<string, () => string> = {
  light: () => t('common.light'),
  dark: () => t('common.dark'),
  amoled: () => t('common.amoled'),
  custom: () => t('settings.themeCustom'),
  system: () => t('common.system'),
}

export function useNavigation() {
  useLocale()
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const { logout } = useAuth()
  const { data: profile } = useProfile()
  const { data: features } = useSWR('settings/features', () => api.settings.getFeatures(), {
    revalidateOnFocus: false,
    dedupingInterval: 300000,
  })
  const [mounted, setMounted] = useState(false)

  // Sidebar config with cross-tab sync
  const [sidebarConfig, setSidebarConfig] = useState(() => getDefaultSidebarConfig())

  useEffect(() => {
    setMounted(true)
    setSidebarConfig(loadSidebarConfig())
  }, [])

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === SIDEBAR_CONFIG_KEY) setSidebarConfig(loadSidebarConfig())
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  // Visible links filtered by role + feature flags
  const visibleLinks = useMemo(() => {
    return sidebarConfig.order
      .map((href) => PAGE_REGISTRY.find((p) => p.href === href))
      .filter(
        (p): p is PageDef =>
          p != null && hasRole(profile?.role, p.minRole ?? 'viewer') && passesFeatureFlag(p, features),
      )
  }, [sidebarConfig.order, profile?.role, features])

  // Grouped links by role tier (for sidebar/mobile nav section headers)
  const groupedLinks = useMemo(() => {
    const groups: { labelKey: string; links: PageDef[] }[] = [
      {
        labelKey: 'nav.sectionBrowse',
        links: visibleLinks.filter((p) => !p.minRole || p.minRole === 'viewer'),
      },
      {
        labelKey: 'nav.sectionManage',
        links: visibleLinks.filter((p) => p.minRole === 'member'),
      },
      {
        labelKey: 'nav.sectionAdmin',
        links: visibleLinks.filter((p) => p.minRole === 'admin'),
      },
    ]
    return groups.filter((g) => g.links.length > 0)
  }, [visibleLinks])

  // Per-link resolved hrefs (last visited URL per tab root). Computed after
  // mount to avoid a hydration mismatch; first render falls back to bare hrefs.
  // Shared by Sidebar + MobileNav so desktop and the mobile drawer match the
  // BottomTabBar's restore behaviour.
  const [resolvedHrefs, setResolvedHrefs] = useState<Record<string, string>>({})
  // Last list-level URL per tab root: where a link goes from a deep page of
  // its own section.
  const [resolvedListHrefs, setResolvedListHrefs] = useState<Record<string, string>>({})

  useEffect(() => {
    const next: Record<string, string> = {}
    const lists: Record<string, string> = {}
    for (const group of groupedLinks) {
      for (const link of group.links) {
        next[link.href] = getTabHref(link.href)
        lists[link.href] = getListHref(link.href)
      }
    }
    setResolvedHrefs(next)
    setResolvedListHrefs(lists)
  }, [groupedLinks, pathname])

  const resolveHref = useCallback(
    (href: string) => {
      // Already inside this section? Point the link at the section's list so
      // the user can always get back to it — not the remembered deep URL, which
      // would be the very sub-page (e.g. a gallery detail) they're on. From a
      // deep page that is the last list-level URL (`/pixiv?tab=bookmarks`), not
      // the bare root, which would be a different list. At the root itself the
      // link stays bare: clicking it only scrolls to top.
      if (pathname === href) return href
      if (href !== '/' && pathname.startsWith(href + '/')) return resolvedListHrefs[href] ?? href
      return resolvedHrefs[href] ?? href
    },
    [pathname, resolvedHrefs, resolvedListHrefs],
  )

  const handleNavClick = useCallback(
    (e: MouseEvent, href: string) => {
      // Only intercept when already exactly at the section root (list level):
      // scroll to top instead of a no-op navigation. On a deeper sub-page, let
      // the link navigate up to the section root; on another tab, let it restore
      // the remembered URL.
      if (pathname !== href) {
        // Restoring a deep sub-page from another section: flag it so the back
        // button there climbs to the section list instead of history-backing
        // into the section we're leaving now.
        const target = resolveHref(href)
        if (target.split('?')[0] !== href) markTabRestore(target)
        return
      }
      e.preventDefault()
      window.scrollTo({ top: 0 })
    },
    [pathname, resolveHref],
  )

  // Theme cycling
  const cycleTheme = useCallback(() => {
    const idx = THEME_CYCLE.indexOf(theme as (typeof THEME_CYCLE)[number])
    setTheme(THEME_CYCLE[(idx + 1) % THEME_CYCLE.length])
  }, [theme, setTheme])

  const themeKey = mounted ? (theme as keyof typeof THEME_ICON) || 'system' : 'system'
  const ThemeIcon = THEME_ICON[themeKey] ?? Monitor
  const themeLabel = THEME_LABEL[themeKey]?.() ?? t('common.theme')

  return {
    profile,
    logout,
    visibleLinks,
    groupedLinks,
    resolveHref,
    handleNavClick,
    cycleTheme,
    ThemeIcon,
    themeLabel,
  }
}
