'use client'

import { AlertDialog } from '@/components/ui/alert-dialog'
import { t } from '@/lib/i18n'

/** Confirm subscribing to the gallery's account; the first check re-fetches what is already held. */
export function SubscribeAccountDialog({
  open,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
      title={t('library.subscribeAccountTitle')}
      description={t('library.subscribeAccountBody')}
      confirmLabel={t('library.subscribeAccountConfirm')}
      onConfirm={onConfirm}
      busy={busy}
    />
  )
}
