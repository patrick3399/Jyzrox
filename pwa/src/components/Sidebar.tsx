'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import { Settings, LogOut, Sun, Moon, Monitor } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PAGE_REGISTRY, hasRole, type PageDef } from '@/lib/pageRegistry'
import { loadSidebarConfig, SIDEBAR_CONFIG_KEY } from '@/components/SidebarConfig'

const themeCycle = ['light', 'dark', 'amoled', 'system'] as const
const themeIcon = { light: Sun, dark: Moon, amoled: Moon, system: Monitor }
const themeLabel = {
  light: () => t('common.light'),
  dark: () => t('common.dark'),
  amoled: () => t('common.amoled'),
  system: () => t('common.system'),
}

export function Sidebar() {
  useLocale()
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const { logout } = useAuth()
  const { data: profile } = useProfile()
  const { data: stats } = useDownloadStats()

  const [sidebarConfig, setSidebarConfig] = useState(() => loadSidebarConfig())

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === SIDEBAR_CONFIG_KEY) setSidebarConfig(loadSidebarConfig())
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  const visibleLinks = useMemo(() => {
    return sidebarConfig.order
      .map((href) => PAGE_REGISTRY.find((p) => p.href === href))
      .filter((p): p is PageDef => p != null && hasRole(profile?.role, p.minRole ?? 'viewer'))
  }, [sidebarConfig.order, profile?.role])

  const cycleTheme = () => {
    const idx = themeCycle.indexOf(theme as (typeof themeCycle)[number])
    setTheme(themeCycle[(idx + 1) % themeCycle.length])
  }

  return (
    <aside className="hidden lg:flex fixed inset-y-0 left-0 z-40 w-56 flex-col bg-vault-card border-r border-vault-border">
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 h-16 shrink-0">
        <span className="text-vault-accent font-bold text-lg tracking-wide">Jyzrox</span>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto no-scrollbar">
        {visibleLinks.map((link) => {
          const Icon = link.icon
          const isActive =
            pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href))
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
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
            </Link>
          )
        })}
      </nav>

      {/* Bottom section */}
      <div className="px-3 py-3 border-t border-vault-border space-y-2">
        {/* User avatar + name */}
        {profile && (
          <div className="flex items-center gap-3 px-3 py-2">
            {}
            <img
              src={profile.avatar_url}
              alt=""
              className="w-8 h-8 rounded-full object-cover bg-vault-input shrink-0"
            />
            <span className="text-sm text-vault-text truncate">{profile.username}</span>
          </div>
        )}

        {/* Settings link */}
        <Link
          href="/settings"
          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
            pathname === '/settings' || pathname.startsWith('/settings')
              ? 'bg-vault-accent/10 text-vault-accent font-medium'
              : 'text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover'
          }`}
        >
          <Settings size={18} />
          <span>{t('nav.settings')}</span>
        </Link>

        {/* Theme toggle */}
        {(() => {
          const key = (theme as keyof typeof themeIcon) || 'system'
          const Icon = themeIcon[key] ?? Monitor
          return (
            <button
              onClick={cycleTheme}
              className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
              title={themeLabel[key]?.() ?? ''}
            >
              <Icon size={18} />
              <span>{themeLabel[key]?.() ?? t('common.theme')}</span>
            </button>
          )
        })()}

        {/* Logout */}
        <button
          onClick={logout}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
        >
          <LogOut size={18} />
          <span>{t('nav.logout')}</span>
        </button>
      </div>
    </aside>
  )
}
