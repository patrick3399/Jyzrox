'use client'

import { useEffect } from 'react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'

export function SWUpdatePrompt() {
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return

    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'SW_UPDATED') {
        toast(t('common.updateAvailable'), {
          description: t('common.updateDescription'),
          action: {
            label: t('common.refresh'),
            onClick: () => window.location.reload(),
          },
          duration: Infinity,
        })
      }
    }

    navigator.serviceWorker.addEventListener('message', handler)
    return () => navigator.serviceWorker.removeEventListener('message', handler)
  }, [])

  return null
}
