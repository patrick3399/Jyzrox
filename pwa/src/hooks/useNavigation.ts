import { useState, useEffect, useMemo, useCallback } from 'react'
import { useTheme } from 'next-themes'
import { Sun, Moon, Monitor } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PAGE_REGISTRY, hasRole, type PageDef } from '@/lib/pageRegistry'
import { loadSidebarConfig, SIDEBAR_CONFIG_KEY } from '@/components/SidebarConfig'

const THEME_CYCLE = ['light', 'dark', 'amoled', 'system'] as const

const THEME_ICON: Record<string, typeof Sun> = {
  light: Sun,
  dark: Moon,
  amoled: Moon,
  system: Monitor,
}

const THEME_LABEL: Record<string, () => string> = {
  light: () => t('common.light'),
  dark: () => t('common.dark'),
  amoled: () => t('common.amoled'),
  system: () => t('common.system'),
}

export function useNavigation() {
  useLocale()
  const { theme, setTheme } = useTheme()
  const { logout } = useAuth()
  const { data: profile } = useProfile()

  // Sidebar config with cross-tab sync
  const [sidebarConfig, setSidebarConfig] = useState(() => loadSidebarConfig())
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === SIDEBAR_CONFIG_KEY) setSidebarConfig(loadSidebarConfig())
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  // Visible links filtered by role
  const visibleLinks = useMemo(() => {
    return sidebarConfig.order
      .map((href) => PAGE_REGISTRY.find((p) => p.href === href))
      .filter((p): p is PageDef => p != null && hasRole(profile?.role, p.minRole ?? 'viewer'))
  }, [sidebarConfig.order, profile?.role])

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

  // Theme cycling
  const cycleTheme = useCallback(() => {
    const idx = THEME_CYCLE.indexOf(theme as (typeof THEME_CYCLE)[number])
    setTheme(THEME_CYCLE[(idx + 1) % THEME_CYCLE.length])
  }, [theme, setTheme])

  const themeKey = (theme as keyof typeof THEME_ICON) || 'system'
  const ThemeIcon = THEME_ICON[themeKey] ?? Monitor
  const themeLabel = THEME_LABEL[themeKey]?.() ?? t('common.theme')

  return {
    profile,
    logout,
    visibleLinks,
    groupedLinks,
    cycleTheme,
    ThemeIcon,
    themeLabel,
  }
}
