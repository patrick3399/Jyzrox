'use client'

import Link from 'next/link'
import { ShieldX } from 'lucide-react'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'

export default function ForbiddenPage() {
  useLocale()
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
      <ShieldX size={64} className="text-vault-text-secondary" />
      <h1 className="text-2xl font-bold text-vault-text">{t('forbidden.title')}</h1>
      <p className="text-vault-text-secondary text-center max-w-md">
        {t('forbidden.description')}
      </p>
      <Link
        href="/"
        className="mt-4 px-6 py-2 rounded-lg bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors"
      >
        {t('forbidden.backHome')}
      </Link>
    </div>
  )
}
