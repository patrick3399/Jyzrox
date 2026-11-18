'use client'

import Link from 'next/link'
import { AlertDialog } from '@/components/ui/alert-dialog'
import { galleryHref } from '@/lib/galleryRoutes'
import { t } from '@/lib/i18n'
import type { ExistingGalleryHint } from './existingGallery'

/** Tell the user a new subscription's account was already downloaded, and let them go look first. */
export function ExistingGalleryDialog({
  hint,
  busy,
  onCancel,
  onConfirm,
}: {
  /** Null keeps the dialog closed. */
  hint: ExistingGalleryHint | null
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
      title={t('subscriptions.existingGalleryTitle')}
      description={
        hint && (
          <>
            <span className="block">
              {t('subscriptions.existingGalleryBody', {
                title: hint.title,
                pages: String(hint.pages),
              })}
            </span>
            <Link
              href={galleryHref(hint.source, hint.sourceId)}
              className="mt-2 inline-block text-vault-accent underline"
            >
              {t('subscriptions.existingGalleryOpen')}
            </Link>
          </>
        )
      }
      confirmLabel={t('subscriptions.existingGalleryConfirm')}
      onConfirm={onConfirm}
      busy={busy}
    />
  )
}
