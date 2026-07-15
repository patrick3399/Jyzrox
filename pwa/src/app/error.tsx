'use client'

import { useEffect } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { t } from '@/lib/i18n'

export default function RouteError({ error, reset }: { error: Error; reset: () => void }) {
  useLocale()

  useEffect(() => {
    console.error('Route rendering failed', error)
  }, [error])

  return (
    <div className="mx-auto max-w-lg rounded-xl border border-red-500/40 bg-red-500/10 p-6 text-center">
      <h2 className="text-lg font-semibold text-red-300">{t('common.loadFailed')}</h2>
      <p className="mt-2 text-sm text-vault-text-muted" role="alert">
        {error.message || t('common.error')}
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-5 rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-white hover:brightness-110"
      >
        {t('common.retry')}
      </button>
    </div>
  )
}
