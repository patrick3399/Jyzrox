'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Settings, LogOut } from 'lucide-react'
import { useNavigation } from '@/hooks/useNavigation'
import { useNavCounts } from '@/hooks/useNavCounts'
import { t } from '@/lib/i18n'

interface SidebarProps {
  downloadStats?: { running: number; finished: number }
}

export function Sidebar({ downloadStats: stats }: SidebarProps) {
  const pathname = usePathname()
  const { profile, logout, groupedLinks, cycleTheme, ThemeIcon, themeLabel } = useNavigation()
  const navCounts = useNavCounts()

  return (
    <aside className="hidden lg:flex fixed inset-y-0 left-0 z-40 w-56 flex-col bg-vault-card border-r border-vault-border">
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 h-16 shrink-0">
        <span className="text-vault-accent font-bold text-lg tracking-wide">Jyzrox</span>
      </div>

      {/* Nav links — grouped by role tier */}
      <nav className="flex-1 px-3 py-2 overflow-y-auto no-scrollbar">
        {groupedLinks.map((section, sectionIdx) => (
          <div key={sectionIdx}>
            {sectionIdx > 0 && <div className="my-1 border-t border-vault-border" />}
            <div className="text-[10px] uppercase tracking-wider text-vault-text-muted px-3 pt-3 pb-1">
              {t(section.labelKey)}
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
                    {link.href === '/trash' && navCounts['/trash'] > 0 && (
                      <span className="ml-auto">
                        <span className="min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-orange-500/20 text-orange-400 text-[10px] font-bold px-1">
                          {navCounts['/trash']}
                        </span>
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
      <div className="px-3 py-3 border-t border-vault-border space-y-2">
        {/* User avatar + name */}
        {profile && (
          <div className="flex items-center gap-3 px-3 py-2">
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
        <button
          onClick={cycleTheme}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
          title={themeLabel}
        >
          <ThemeIcon size={18} />
          <span>{themeLabel}</span>
        </button>

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
