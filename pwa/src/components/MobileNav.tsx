'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import {
  LayoutDashboard,
  Search,
  BookOpen,
  Clock,
  Download,
  Tags,
  Settings,
  LogOut,
  Sun,
  Moon,
  Monitor,
  Menu,
  X,
  PackageOpen,
  FolderInput,
  Key,
  Puzzle,
  Palette,
} from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'

const navLinks = [
  { href: '/', label: () => t('nav.dashboard'), icon: LayoutDashboard },
  { href: '/browse', label: () => t('nav.browse'), icon: Search },
  { href: '/pixiv', label: () => t('nav.pixiv'), icon: Palette },
  { href: '/library', label: () => t('nav.library'), icon: BookOpen },
  { href: '/history', label: () => t('nav.history'), icon: Clock },
  { href: '/queue', label: () => t('nav.queue'), icon: Download },
  { href: '/tags', label: () => t('nav.tags'), icon: Tags },
  { href: '/export', label: () => t('nav.export'), icon: PackageOpen },
  { href: '/import', label: () => t('nav.import'), icon: FolderInput },
  { href: '/credentials', label: () => t('nav.credentials'), icon: Key },
  { href: '/plugins', label: () => t('nav.plugins'), icon: Puzzle },
  { href: '/settings', label: () => t('nav.settings'), icon: Settings },
]

const themeCycle = ['light', 'dark', 'system'] as const
const themeIcon: Record<string, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }
const themeLabel: Record<string, () => string> = {
  light: () => t('common.light'),
  dark: () => t('common.dark'),
  system: () => t('common.system'),
}

export function MobileNav() {
  useLocale()
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const { logout } = useAuth()
  const { data: profile } = useProfile()
  const { data: stats } = useDownloadStats()
  const [open, setOpen] = useState(false)

  // Close drawer on route change
  useEffect(() => {
    setOpen(false)
  }, [pathname])

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

  const ThemeIcon = themeIcon[theme ?? 'system'] ?? Monitor
  const key = (theme as keyof typeof themeLabel) || 'system'

  return (
    <>
      {/* Top bar — pt accounts for iOS safe area (notch / Dynamic Island) */}
      <nav
        className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-vault-card border-b border-vault-border h-14 flex items-center px-3 gap-2"
        style={{ paddingTop: 'var(--sat)', height: 'calc(3.5rem + var(--sat))' }}
      >
        <button
          onClick={() => setOpen(true)}
          className="p-2 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
          aria-label={t('nav.openMenu')}
        >
          <Menu size={20} />
        </button>

        <span className="text-vault-accent font-bold text-lg tracking-wide flex-1">Jyzrox</span>
      </nav>

      {/* Backdrop */}
      <div
        className={`lg:hidden fixed inset-0 z-50 bg-black/50 backdrop-blur-sm transition-opacity duration-200 ${
          open ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={() => setOpen(false)}
      />

      {/* Drawer */}
      <aside
        className={`lg:hidden fixed inset-y-0 left-0 z-50 w-64 max-w-[80vw] bg-vault-card border-r border-vault-border flex flex-col transition-transform duration-200 ${
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
            onClick={() => setOpen(false)}
            className="p-1.5 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
            aria-label={t('nav.closeMenu')}
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
          {navLinks.map((link) => {
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
                <span>{link.label()}</span>
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
        <div className="px-3 py-3 border-t border-vault-border space-y-1">
          <button
            onClick={cycleTheme}
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
