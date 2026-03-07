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
} from 'lucide-react'
import { t } from '@/lib/i18n'

const navLinks = [
  { href: '/', label: () => t('nav.dashboard'), icon: LayoutDashboard },
  { href: '/browse', label: () => t('nav.browse'), icon: Search },
  { href: '/library', label: () => t('nav.library'), icon: BookOpen },
  { href: '/queue', label: () => t('nav.queue'), icon: Download },
  { href: '/tags', label: () => t('nav.tags'), icon: Tags },
  { href: '/settings', label: () => t('nav.settings'), icon: Settings },
]

const themeCycle = ['light', 'dark', 'system'] as const
const themeIcon: Record<string, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }

export function MobileNav() {
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()

  const cycleTheme = () => {
    const idx = themeCycle.indexOf(theme as typeof themeCycle[number])
    setTheme(themeCycle[(idx + 1) % themeCycle.length])
  }

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    window.location.href = '/login'
  }

  return (
    <nav className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-vault-card border-b border-vault-border h-14 flex items-center px-3 gap-1">
      <span className="text-vault-accent font-bold text-lg tracking-wide mr-3 shrink-0">
        Jyzrox
      </span>
      <div className="flex items-center gap-0.5 overflow-x-auto flex-1">
        {navLinks.map((link) => {
          const Icon = link.icon
          const isActive = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href))
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm transition-colors whitespace-nowrap ${
                isActive
                  ? 'text-vault-accent bg-vault-accent/10'
                  : 'text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover'
              }`}
            >
              <Icon size={16} />
              <span className="hidden sm:inline">{link.label()}</span>
            </Link>
          )
        })}
      </div>
      <button
        onClick={cycleTheme}
        className="shrink-0 p-2 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
        title={t('common.theme')}
      >
        {(() => { const Icon = themeIcon[theme ?? 'system'] ?? Monitor; return <Icon size={18} /> })()}
      </button>
      <button
        onClick={handleLogout}
        className="shrink-0 p-2 rounded-lg text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
        title={t('nav.logout')}
      >
        <LogOut size={18} />
      </button>
    </nav>
  )
}
