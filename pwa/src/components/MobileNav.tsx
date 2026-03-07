'use client'

import { useState, useEffect, useCallback } from 'react'
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
  Menu,
  X,
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

const themeCycle = ['light', 'dark', 'system'] as const
const themeIcon: Record<string, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }
const themeLabel: Record<string, () => string> = {
  light: () => t('common.light'),
  dark: () => t('common.dark'),
  system: () => t('common.system'),
}

export function MobileNav() {
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)

  // Close drawer on route change
  useEffect(() => {
    setOpen(false)
  }, [pathname])

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
      return () => { document.body.style.overflow = '' }
    }
  }, [open])

  const cycleTheme = useCallback(() => {
    const idx = themeCycle.indexOf(theme as typeof themeCycle[number])
    setTheme(themeCycle[(idx + 1) % themeCycle.length])
  }, [theme, setTheme])

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    window.location.href = '/login'
  }

  const ThemeIcon = themeIcon[theme ?? 'system'] ?? Monitor
  const key = (theme as keyof typeof themeLabel) || 'system'

  return (
    <>
      {/* Top bar */}
      <nav className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-vault-card border-b border-vault-border h-14 flex items-center px-3 gap-2">
        <button
          onClick={() => setOpen(true)}
          className="p-2 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
          aria-label="Open menu"
        >
          <Menu size={20} />
        </button>

        <span className="text-vault-accent font-bold text-lg tracking-wide flex-1">
          Jyzrox
        </span>

        <button
          onClick={cycleTheme}
          className="p-2 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
          title={t('common.theme')}
        >
          <ThemeIcon size={18} />
        </button>
        <button
          onClick={handleLogout}
          className="p-2 rounded-lg text-vault-text-secondary hover:text-red-400 hover:bg-red-500/10 transition-colors"
          title={t('nav.logout')}
        >
          <LogOut size={18} />
        </button>
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
        {/* Drawer header */}
        <div className="flex items-center justify-between px-4 h-14 shrink-0 border-b border-vault-border">
          <span className="text-vault-accent font-bold text-lg tracking-wide">Jyzrox</span>
          <button
            onClick={() => setOpen(false)}
            className="p-1.5 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
          {navLinks.map((link) => {
            const Icon = link.icon
            const isActive = pathname === link.href || (link.href !== '/' && pathname.startsWith(link.href))
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
            onClick={handleLogout}
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
