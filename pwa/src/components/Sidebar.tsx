'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import {
  LayoutDashboard,
  Search,
  BookOpen,
  Download,
  Tags,
  Settings,
  LogOut,
  Sun,
  Moon,
  Monitor,
  PackageOpen,
} from 'lucide-react'
import { t } from '@/lib/i18n'

const navLinks = [
  { href: '/', label: () => t('nav.dashboard'), icon: LayoutDashboard },
  { href: '/browse', label: () => t('nav.browse'), icon: Search },
  { href: '/library', label: () => t('nav.library'), icon: BookOpen },
  { href: '/queue', label: () => t('nav.queue'), icon: Download },
  { href: '/tags', label: () => t('nav.tags'), icon: Tags },
  { href: '/export', label: () => t('nav.export'), icon: PackageOpen },
  { href: '/settings', label: () => t('nav.settings'), icon: Settings },
]

const themeOptions = [
  { value: 'light', icon: Sun, label: () => t('common.light') },
  { value: 'dark', icon: Moon, label: () => t('common.dark') },
  { value: 'system', icon: Monitor, label: () => t('common.system') },
]

export function Sidebar() {
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    window.location.href = '/login'
  }

  return (
    <aside className="hidden lg:flex fixed inset-y-0 left-0 z-40 w-56 flex-col bg-vault-card border-r border-vault-border">
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 h-16 shrink-0">
        <span className="text-vault-accent font-bold text-lg tracking-wide">
          Jyzrox
        </span>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
        {navLinks.map((link) => {
          const Icon = link.icon
          const isActive = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href))
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
            </Link>
          )
        })}
      </nav>

      {/* Bottom section */}
      <div className="px-3 py-3 border-t border-vault-border space-y-2">
        {/* Theme switcher */}
        <div className="flex items-center gap-1 bg-vault-input rounded-lg p-1">
          {themeOptions.map((opt) => {
            const Icon = opt.icon
            const isActive = theme === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => setTheme(opt.value)}
                title={opt.label()}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded text-xs transition-colors ${
                  isActive
                    ? 'bg-vault-card-hover text-vault-text shadow-sm'
                    : 'text-vault-text-muted hover:text-vault-text-secondary'
                }`}
              >
                <Icon size={14} />
              </button>
            )
          })}
        </div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
        >
          <LogOut size={18} />
          <span>{t('nav.logout')}</span>
        </button>
      </div>
    </aside>
  )
}
