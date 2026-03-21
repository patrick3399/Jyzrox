'use client'

import Link from 'next/link'
import { t } from '@/lib/i18n'
import type { SettingsCategoryDef } from '@/lib/settingsRegistry'

interface SettingsCardProps {
  category: SettingsCategoryDef
}

export function SettingsCard({ category }: SettingsCardProps) {
  const Icon = category.icon
  return (
    <Link
      href={`/settings/${category.slug}`}
      className="flex flex-col items-center gap-2 p-4 rounded-xl bg-vault-card border border-vault-border hover:border-vault-accent/50 hover:bg-vault-card-hover transition-colors text-center group"
    >
      <Icon
        size={24}
        className="text-vault-text-secondary group-hover:text-vault-accent transition-colors"
      />
      <span className="text-sm font-medium text-vault-text">{t(category.labelKey)}</span>
      <span className="text-xs text-vault-text-muted leading-tight">{t(category.descKey)}</span>
    </Link>
  )
}
