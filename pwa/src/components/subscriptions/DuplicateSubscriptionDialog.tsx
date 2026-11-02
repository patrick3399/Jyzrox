'use client'

import { AlertDialog } from '@/components/ui/alert-dialog'
import { t } from '@/lib/i18n'
import type { DuplicateSubscriptionHint } from './duplicateSubscription'

/** Ask before a submitted form overwrites the subscription its URL already belongs to. */
export function DuplicateSubscriptionDialog({
  hint,
  busy,
  onCancel,
  onConfirm,
}: {
  /** Null keeps the dialog closed. */
  hint: DuplicateSubscriptionHint | null
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <AlertDialog
      open={hint !== null}
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
      title={t('subscriptions.duplicateTitle')}
      description={t('subscriptions.duplicateBody', { name: hint?.name ?? hint?.url ?? '' })}
      confirmLabel={t('subscriptions.duplicateConfirm')}
      onConfirm={onConfirm}
      busy={busy}
    />
  )
}
