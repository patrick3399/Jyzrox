'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ChevronRight, Settings } from 'lucide-react'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { t } from '@/lib/i18n'
import { getSettingsGroups, SETTINGS_CATEGORIES } from '@/lib/settingsRegistry'

export function SettingsLayoutShell({ children }: { children: React.ReactNode }) {
  useLocale()
  const pathname = usePathname()
  const { data: profile } = useProfile()
  const groups = getSettingsGroups(profile?.role)
  const currentSlug = pathname?.startsWith('/settings/') ? pathname.split('/')[2] : ''
  const currentCategory = SETTINGS_CATEGORIES.find((category) => category.slug === currentSlug)

  return (
    <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-20 lg:self-start">
        <nav
          aria-label={t('settings.title')}
          className="rounded-xl border border-vault-border bg-vault-card/70 p-2"
        >
          <Link
            href="/settings"
            aria-current={pathname === '/settings' ? 'page' : undefined}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${
              pathname === '/settings'
                ? 'bg-vault-accent/15 text-vault-accent'
                : 'text-vault-text-secondary hover:bg-vault-card-hover hover:text-vault-text'
            }`}
          >
            <Settings size={16} />
            <span>{t('settings.title')}</span>
          </Link>

          <div className="mt-2 max-h-[38vh] space-y-3 overflow-y-auto pr-1 lg:max-h-none">
            {groups.map((group) => (
              <div key={group.group}>
                <p className="px-3 pb-1 pt-2 text-[10px] uppercase tracking-wide text-vault-text-muted">
                  {t(group.labelKey)}
                </p>
                <div className="space-y-1">
                  {group.categories.map((category) => {
                    const href = `/settings/${category.slug}`
                    const active = pathname === href
                    const Icon = category.icon
                    return (
                      <Link
                        key={category.slug}
                        href={href}
                        aria-current={active ? 'page' : undefined}
                        className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${
                          active
                            ? 'bg-vault-accent/15 text-vault-accent'
                            : 'text-vault-text-secondary hover:bg-vault-card-hover hover:text-vault-text'
                        }`}
                      >
                        <Icon size={16} className="shrink-0" />
                        <span className="truncate">{t(category.labelKey)}</span>
                      </Link>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </nav>
      </aside>

      <div className="min-w-0">
        {currentCategory && (
          <div className="mb-4 flex items-center gap-1 text-xs text-vault-text-muted">
            <Link href="/settings" className="hover:text-vault-text-secondary">
              {t('settings.title')}
            </Link>
            <ChevronRight size={14} />
            <span className="text-vault-text-secondary">{t(currentCategory.labelKey)}</span>
          </div>
        )}
        {children}
      </div>
    </div>
  )
}
