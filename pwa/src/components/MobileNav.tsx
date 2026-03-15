'use client'

import { useEffect, useCallback } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import {
  LayoutDashboard,
  Compass,
  BookOpen,
  Clock,
  Download,
  Tags,
  Settings,
  LogOut,
  Sun,
  Moon,
  Monitor,
  X,
  PackageOpen,
  FolderInput,
  Key,
  Puzzle,
  Palette,
  Users,
  FolderTree,
  Rss,
  CalendarClock,
  ScanSearch,
  ShieldCheck,
  Images,
  Trash2,
} from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { useNavCounts } from '@/hooks/useNavCounts'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { UserRole } from '@/lib/types'

function hasRole(userRole: string | undefined, minRole: UserRole): boolean {
  const ROLE_LEVEL: Record<string, number> = { admin: 3, member: 2, viewer: 1 }
  return (ROLE_LEVEL[userRole || 'viewer'] ?? 0) >= ROLE_LEVEL[minRole]
}

const navSections = [
  {
    label: () => t('nav.sectionBrowse'),
    links: [
      { href: '/', label: () => t('nav.dashboard'), icon: LayoutDashboard, minRole: 'viewer' as UserRole },
      { href: '/e-hentai', label: () => t('nav.ehentai'), icon: Compass, minRole: 'viewer' as UserRole },
      { href: '/pixiv', label: () => t('nav.pixiv'), icon: Palette, minRole: 'viewer' as UserRole },
      { href: '/library', label: () => t('nav.library'), icon: BookOpen, minRole: 'viewer' as UserRole },
      { href: '/trash', label: () => t('nav.trash'), icon: Trash2, minRole: 'viewer' as UserRole },
      { href: '/images', label: () => t('nav.images'), icon: Images, minRole: 'viewer' as UserRole },
      { href: '/explorer', label: () => t('nav.explorer'), icon: FolderTree, minRole: 'viewer' as UserRole },
      { href: '/artists', label: () => t('nav.artists'), icon: Users, minRole: 'viewer' as UserRole },
      { href: '/history', label: () => t('nav.history'), icon: Clock, minRole: 'viewer' as UserRole },
    ],
  },
  {
    label: () => t('nav.sectionManage'),
    links: [
      { href: '/subscriptions', label: () => t('nav.subscriptions'), icon: Rss, minRole: 'member' as UserRole },
      { href: '/queue', label: () => t('nav.queue'), icon: Download, minRole: 'member' as UserRole },
      { href: '/tags', label: () => t('nav.tags'), icon: Tags, minRole: 'viewer' as UserRole },
      { href: '/export', label: () => t('nav.export'), icon: PackageOpen, minRole: 'member' as UserRole },
      { href: '/import', label: () => t('nav.import'), icon: FolderInput, minRole: 'member' as UserRole },
    ],
  },
  {
    label: () => t('nav.sectionAdmin'),
    links: [
      { href: '/scheduled-tasks', label: () => t('nav.scheduledTasks'), icon: CalendarClock, minRole: 'admin' as UserRole },
      { href: '/dedup', label: () => t('nav.dedup'), icon: ScanSearch, minRole: 'admin' as UserRole },
      { href: '/credentials', label: () => t('nav.credentials'), icon: Key, minRole: 'admin' as UserRole },
      { href: '/plugins', label: () => t('nav.plugins'), icon: Puzzle, minRole: 'admin' as UserRole },
      { href: '/admin/users', label: () => t('nav.users'), icon: ShieldCheck, minRole: 'admin' as UserRole },
    ],
  },
]

const themeCycle = ['light', 'dark', 'amoled', 'system'] as const
const themeIcon: Record<string, typeof Sun> = { light: Sun, dark: Moon, amoled: Moon, system: Monitor }
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
          {navSections.map((section, sectionIdx) => {
            const visibleLinks = section.links.filter(link => hasRole(profile?.role, link.minRole))
            if (visibleLinks.length === 0) return null
            return (
              <div key={sectionIdx}>
                {sectionIdx > 0 && (
                  <div className="my-1 border-t border-vault-border" />
                )}
                <div className="text-[10px] uppercase tracking-wider text-vault-text-muted px-3 pt-3 pb-1">
                  {section.label()}
                </div>
                <div className="space-y-0.5">
                  {visibleLinks.map((link) => {
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
                        {link.href !== '/queue' && (navCounts[link.href as keyof typeof navCounts] ?? 0) > 0 && (
                          <span className="ml-auto min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-vault-accent/20 text-vault-accent text-[10px] font-bold px-1">
                            {navCounts[link.href as keyof typeof navCounts]}
                          </span>
                        )}
                      </Link>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </nav>

        {/* Bottom section */}
        <div className="px-3 pt-3 border-t border-vault-border space-y-1" style={{ paddingBottom: 'calc(0.75rem + var(--sab))' }}>
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
