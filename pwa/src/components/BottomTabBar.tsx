'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Compass, Palette, BookOpen, Download, Menu } from 'lucide-react'
import { useDownloadStats } from '@/hooks/useDownloadQueue'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'

interface BottomTabBarProps {
  onMoreClick: () => void
}

const tabs = [
  { href: '/e-hentai', labelKey: 'nav.ehentai', icon: Compass },
  { href: '/pixiv', labelKey: 'nav.pixiv', icon: Palette },
  { href: '/library', labelKey: 'nav.library', icon: BookOpen },
  { href: '/queue', labelKey: 'nav.queue', icon: Download },
] as const

export function BottomTabBar({ onMoreClick }: BottomTabBarProps) {
  useLocale()
  const pathname = usePathname()
  const { data: stats } = useDownloadStats()

  if (pathname.startsWith('/reader/')) return null

  return (
    <nav
      className="lg:hidden fixed bottom-0 left-0 right-0 z-50 bg-vault-card border-t border-vault-border flex"
      style={{ paddingBottom: 'var(--sab)', height: 'calc(4rem + var(--sab))' }}
    >
      {tabs.map(({ href, labelKey, icon: Icon }) => {
        const isActive = pathname === href || pathname.startsWith(href)
        return (
          <Link
            key={href}
            href={href}
            className={`flex flex-col items-center justify-center flex-1 gap-1 text-xs transition-colors relative ${
              isActive
                ? 'text-vault-accent'
                : 'text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            <span className="relative">
              <Icon size={22} />
              {href === '/queue' && stats && (
                <>
                  {stats.running > 0 && (
                    <span className="absolute -top-1.5 -right-2 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-blue-500 text-white text-[9px] font-bold px-1 leading-none">
                      {stats.running}
                    </span>
                  )}
                  {stats.running === 0 && stats.finished > 0 && (
                    <span className="absolute -top-1.5 -right-2 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-green-500 text-white text-[9px] font-bold px-1 leading-none">
                      {stats.finished}
                    </span>
                  )}
                </>
              )}
            </span>
            <span>{t(labelKey)}</span>
          </Link>
        )
      })}

      {/* More button */}
      <button
        onClick={onMoreClick}
        className="flex flex-col items-center justify-center flex-1 gap-1 text-xs transition-colors text-vault-text-secondary hover:text-vault-text"
        aria-label={t('nav.more')}
      >
        <Menu size={22} />
        <span>{t('nav.more')}</span>
      </button>
    </nav>
  )
}
