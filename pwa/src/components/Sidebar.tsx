'use client'

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
} from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { useProfile } from '@/hooks/useProfile'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { UserRole } from '@/lib/types'

function hasRole(userRole: string | undefined, minRole: UserRole): boolean {
  const ROLE_LEVEL: Record<string, number> = { admin: 3, member: 2, viewer: 1 }
  return (ROLE_LEVEL[userRole || 'viewer'] ?? 0) >= ROLE_LEVEL[minRole]
}

const navLinks = [
  { href: '/', label: () => t('nav.dashboard'), icon: LayoutDashboard, minRole: 'viewer' as UserRole },
  { href: '/e-hentai', label: () => t('nav.ehentai'), icon: Compass, minRole: 'viewer' as UserRole },
  { href: '/pixiv', label: () => t('nav.pixiv'), icon: Palette, minRole: 'viewer' as UserRole },
  { href: '/library', label: () => t('nav.library'), icon: BookOpen, minRole: 'viewer' as UserRole },
  { href: '/images', label: () => t('nav.images'), icon: Images, minRole: 'viewer' as UserRole },
  { href: '/explorer', label: () => t('nav.explorer'), icon: FolderTree, minRole: 'viewer' as UserRole },
  { href: '/artists', label: () => t('nav.artists'), icon: Users, minRole: 'viewer' as UserRole },
  { href: '/subscriptions', label: () => t('nav.subscriptions'), icon: Rss, minRole: 'member' as UserRole },
  { href: '/history', label: () => t('nav.history'), icon: Clock, minRole: 'viewer' as UserRole },
  { href: '/queue', label: () => t('nav.queue'), icon: Download, minRole: 'member' as UserRole },
  { href: '/tags', label: () => t('nav.tags'), icon: Tags, minRole: 'viewer' as UserRole },
  { href: '/export', label: () => t('nav.export'), icon: PackageOpen, minRole: 'member' as UserRole },
  { href: '/import', label: () => t('nav.import'), icon: FolderInput, minRole: 'member' as UserRole },
  { href: '/scheduled-tasks', label: () => t('nav.scheduledTasks'), icon: CalendarClock, minRole: 'admin' as UserRole },
  { href: '/dedup', label: () => t('nav.dedup'), icon: ScanSearch, minRole: 'admin' as UserRole },
  { href: '/credentials', label: () => t('nav.credentials'), icon: Key, minRole: 'admin' as UserRole },
  { href: '/plugins', label: () => t('nav.plugins'), icon: Puzzle, minRole: 'admin' as UserRole },
  { href: '/admin/users', label: () => t('nav.users'), icon: ShieldCheck, minRole: 'admin' as UserRole },
]

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
      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
        {navLinks.filter(link => hasRole(profile?.role, link.minRole)).map((link) => {
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
