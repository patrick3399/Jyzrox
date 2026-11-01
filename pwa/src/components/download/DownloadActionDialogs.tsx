'use client'

import { useState } from 'react'
import { t } from '@/lib/i18n'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

// ── Shell ─────────────────────────────────────────────────────────────

function DialogShell({
  title,
  busy,
  onClose,
  footer,
  children,
}: {
  title: string
  busy: boolean
  onClose: () => void
  footer?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      title={title}
      dismissible={!busy}
      padded={false}
      footer={footer}
    >
      {children}
    </Dialog>
  )
}

// ── Enqueue refused: the URL is already a subscription ────────────────

/** The subscription an enqueue was refused for (409 `{code: "subscribed"}`). */
export interface SubscribedUrlHint {
  /** Null when the server did not say which subscription matched. */
  subscriptionId: number | null
  name: string | null
}

/**
 * Read the "this URL is already subscribed" refusal out of an error thrown by
 * the API client. The client keeps the parsed `detail` on the error; anything
 * else (a plain Error, a different 409, a string detail) is not a hint.
 */
export function subscribedHint(err: unknown): SubscribedUrlHint | null {
  if (typeof err !== 'object' || err === null) return null
  const detail = (err as { detail?: unknown }).detail
  if (typeof detail !== 'object' || detail === null) return null
  const body = detail as { code?: unknown; subscription_id?: unknown; name?: unknown }
  if (body.code !== 'subscribed') return null
  const id = Number(body.subscription_id)
  return {
    subscriptionId: body.subscription_id != null && Number.isFinite(id) ? id : null,
    name: typeof body.name === 'string' && body.name ? body.name : null,
  }
}

/** Offer "check now" before a manual download resumes history the user may have given up. */
export function SubscribedUrlDialog({
  name,
  canCheck,
  busy,
  onCheck,
  onDownloadAnyway,
  onClose,
}: {
  name: string
  /** False when the server did not identify the subscription, so there is nothing to check. */
  canCheck: boolean
  busy: boolean
  onCheck: () => void
  onDownloadAnyway: () => void
  onClose: () => void
}) {
  return (
    <DialogShell
      title={t('queue.subscribedTitle')}
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <Button
            data-testid="subscribed-download-anyway"
            onClick={onDownloadAnyway}
            disabled={busy}
          >
            {t('queue.downloadAnyway')}
          </Button>
          {canCheck && (
            <Button
              variant="primary"
              autoFocus
              data-testid="subscribed-check-now"
              onClick={onCheck}
              disabled={busy}
            >
              {t('queue.checkSubscriptionNow')}
            </Button>
          )}
        </>
      }
    >
      <div
        className="space-y-2 p-5 text-sm text-vault-text-secondary"
        data-testid="subscribed-dialog"
      >
        <p>{t('queue.subscribedBody', { name })}</p>
      </div>
    </DialogShell>
  )
}

// ── Gallery repair ────────────────────────────────────────────────────

/**
 * Confirm a gallery repair. Only shown when the gallery has purged images,
 * because a repair skips those unless the user asks for them back.
 */
export function RepairGalleryDialog({
  excludedCount,
  busy,
  onConfirm,
  onClose,
}: {
  excludedCount: number
  busy: boolean
  onConfirm: (includeExcluded: boolean) => void
  onClose: () => void
}) {
  const [includeExcluded, setIncludeExcluded] = useState(false)

  return (
    <DialogShell
      title={t('library.repairDialogTitle')}
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            autoFocus
            data-testid="repair-confirm"
            onClick={() => onConfirm(includeExcluded)}
            disabled={busy}
          >
            {t('library.repairStart')}
          </Button>
        </>
      }
    >
      <div className="space-y-4 p-5 text-sm text-vault-text-secondary" data-testid="repair-dialog">
        <p>{t('library.repairDialogBody')}</p>
        <label className="flex cursor-pointer items-start gap-2">
          <input
            type="checkbox"
            data-testid="repair-include-excluded"
            checked={includeExcluded}
            disabled={busy}
            onChange={(e) => setIncludeExcluded(e.target.checked)}
            className="mt-0.5 accent-vault-accent"
          />
          <span>{t('library.repairIncludeExcluded', { count: String(excludedCount) })}</span>
        </label>
      </div>
    </DialogShell>
  )
}
