'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { Key } from 'lucide-react'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { t } from '@/lib/i18n'
import { getSettingsGroups } from '@/lib/settingsRegistry'
import { SettingsCard } from '@/components/settings/SettingsCard'

export default function SettingsPage() {
  useLocale()
  const { data: profile } = useProfile()
  const groups = useMemo(() => getSettingsGroups(profile?.role), [profile?.role])

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settings.title')}</h1>

      {/* Credentials quick link */}
      <Link
        href="/credentials"
        className="flex items-center gap-2 mb-6 px-4 py-2.5 bg-vault-card border border-vault-border rounded-xl text-sm text-vault-text-secondary hover:text-vault-accent hover:border-vault-accent/50 transition-colors w-full"
      >
        <Key size={16} />
        <span>{t('credentials.manageCredentials')}</span>
      </Link>

      <div className="space-y-8">
        {groups.map((group) => (
          <div key={group.group}>
            <h2 className="text-xs uppercase tracking-wider text-vault-text-muted mb-3 px-1">
              {t(group.labelKey)}
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {group.categories.map((cat) => (
                <SettingsCard key={cat.slug} category={cat} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
