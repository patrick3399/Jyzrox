'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import { Settings, LogOut, Sun, Moon, Monitor, X } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { useNavCounts } from '@/hooks/useNavCounts'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PAGE_REGISTRY, hasRole, type PageDef } from '@/lib/pageRegistry'
import { loadSidebarConfig, SIDEBAR_CONFIG_KEY } from '@/components/SidebarConfig'

const themeCycle = ['light', 'dark', 'amoled', 'system'] as const
const themeIcon: Record<string, typeof Sun> = {
  light: Sun,
  dark: Moon,
  amoled: Moon,
  system: Monitor,
}
const themeLabel: Record<string, () => string> = {
  light: () => t('common.light'),
  dark: () => t('common.dark'),
  amoled: () => t('common.amoled'),
  system: () => t('common.system'),
}

interface MobileNavProps {
  open: boolean
  onClose: () => void
}

export function MobileNav({ open, onClose }: MobileNavProps) {
  useLocale()
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const { logout } = useAuth()
  const { data: profile } = useProfile()
  const { data: stats } = useDownloadStats()
  const navCounts = useNavCounts()

  const [sidebarConfig, setSidebarConfig] = useState(() => loadSidebarConfig())

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === SIDEBAR_CONFIG_KEY) setSidebarConfig(loadSidebarConfig())
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  // Close drawer on route change
  useEffect(() => {
    onClose()
  }, [pathname, onClose])

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = ''
      }
    }
  }, [open])

  const cycleTheme = useCallback(() => {
    const idx = themeCycle.indexOf(theme as (typeof themeCycle)[number])
    setTheme(themeCycle[(idx + 1) % themeCycle.length])
  }, [theme, setTheme])

  const sections = useMemo(() => {
    const allVisible = sidebarConfig.order
      .map((href) => PAGE_REGISTRY.find((p) => p.href === href))
      .filter((p): p is PageDef => p != null && hasRole(profile?.role, p.minRole ?? 'viewer'))

    const groups: { label: () => string; links: PageDef[] }[] = [
      {
        label: () => t('nav.sectionBrowse'),
        links: allVisible.filter((p) => !p.minRole || p.minRole === 'viewer'),
      },
      {
        label: () => t('nav.sectionManage'),
        links: allVisible.filter((p) => p.minRole === 'member'),
      },
      {
        label: () => t('nav.sectionAdmin'),
        links: allVisible.filter((p) => p.minRole === 'admin'),
      },
    ]
    return groups.filter((g) => g.links.length > 0)
  }, [sidebarConfig.order, profile?.role])

  const ThemeIcon = themeIcon[theme ?? 'system'] ?? Monitor
  const key = (theme as keyof typeof themeLabel) || 'system'

  return (
    <>
      {/* Backdrop */}
      <div
        className={`lg:hidden fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm transition-opacity duration-200 ${
          open ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />

      {/* Drawer */}
      <aside
        className={`lg:hidden fixed inset-y-0 left-0 z-[60] w-64 max-w-[80vw] bg-vault-card border-r border-vault-border flex flex-col transition-transform duration-200 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Drawer header — pt for iOS safe area */}
        <div
          className="flex items-center justify-between px-4 shrink-0 border-b border-vault-border"
          style={{ paddingTop: 'var(--sat)', minHeight: 'calc(3.5rem + var(--sat))' }}
        >
          <div className="flex items-center gap-2">
            {profile && (
              <img
                src={profile.avatar_url}
                alt=""
                className="w-7 h-7 rounded-full object-cover bg-vault-input shrink-0"
              />
            )}
            <span className="text-vault-accent font-bold text-lg tracking-wide">Jyzrox</span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
            aria-label={t('nav.closeMenu')}
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 py-3 overflow-y-auto no-scrollbar">
          {sections.map((section, sectionIdx) => (
            <div key={sectionIdx}>
              {sectionIdx > 0 && <div className="my-1 border-t border-vault-border" />}
              <div className="text-[10px] uppercase tracking-wider text-vault-text-muted px-3 pt-3 pb-1">
                {section.label()}
              </div>
              <div className="space-y-0.5">
                {section.links.map((link) => {
                  const Icon = link.icon
                  const isActive =
                    pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href))
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                        isActive
                          ? 'bg-vault-accent/10 text-vault-accent font-medium'
                          : 'text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover'
                      }`}
                    >
                      <Icon size={18} />
                      <span>{t(link.labelKey)}</span>
                      {link.href === '/queue' && stats && (
                        <span className="ml-auto flex items-center gap-1">
                          {stats.running > 0 && (
                            <span className="min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-blue-500/20 text-blue-400 text-[10px] font-bold px-1">
                              {stats.running}
                            </span>
                          )}
                          {stats.finished > 0 && (
                            <span className="min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-green-500/20 text-green-400 text-[10px] font-bold px-1">
                              {stats.finished}
                            </span>
                          )}
                        </span>
                      )}
                      {link.href !== '/queue' &&
                        (navCounts[link.href as keyof typeof navCounts] ?? 0) > 0 && (
                          <span className="ml-auto min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-vault-accent/20 text-vault-accent text-[10px] font-bold px-1">
                            {navCounts[link.href as keyof typeof navCounts]}
                          </span>
                        )}
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Bottom section */}
        <div
          className="px-3 pt-3 border-t border-vault-border space-y-1"
          style={{ paddingBottom: 'calc(0.75rem + var(--sab))' }}
        >
          {/* Settings link */}
          <Link
            href="/settings"
            className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
              pathname === '/settings' || pathname.startsWith('/settings')
                ? 'bg-vault-accent/10 text-vault-accent font-medium'
                : 'text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover'
            }`}
          >
            <Settings size={18} />
            <span>{t('nav.settings')}</span>
          </Link>
          <button
            onClick={cycleTheme}
            title={themeLabel[key]?.() ?? ''}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
          >
            <ThemeIcon size={18} />
            <span>{themeLabel[key]?.() ?? t('common.theme')}</span>
          </button>
          <button
            onClick={logout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut size={18} />
            <span>{t('nav.logout')}</span>
          </button>
        </div>
      </aside>
    </>
  )
}
