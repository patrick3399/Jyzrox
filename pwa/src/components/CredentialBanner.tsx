'use client'

import { useState } from 'react'
import Link from 'next/link'
import { X as XIcon } from 'lucide-react'
import { t } from '@/lib/i18n'

export function CredentialBanner({ source }: { source: string }) {
  const [dismissed, setDismissed] = useState(() => {
    if (typeof window === 'undefined') return true
    return localStorage.getItem(`credential_banner_dismissed_${source}`) === 'true'
  })

  if (dismissed) return null

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm">
      <div className="flex items-center gap-2">
        <span>⚠️</span>
        <span>{t('credential.banner.limited')}</span>
        <Link href="/credentials" className="underline hover:text-amber-200 font-medium">
          {t('credential.banner.configure')}
        </Link>
      </div>
      <button
        onClick={() => {
          setDismissed(true)
          localStorage.setItem(`credential_banner_dismissed_${source}`, 'true')
        }}
        className="text-amber-400 hover:text-amber-200 shrink-0"
        aria-label={t('credential.banner.dismiss')}
      >
        <XIcon className="w-4 h-4" />
      </button>
    </div>
  )
}
