'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { t } from '@/lib/i18n'

// ── Shell ─────────────────────────────────────────────────────────────

function DialogShell({
  title,
  busy,
  onClose,
  children,
}: {
  title: string
  busy: boolean
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // Pages that bind Escape on window ("go back") must not also run: this
      // document listener fires first, so mark the key handled.
      e.preventDefault()
      e.stopPropagation()
      if (!busy) onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      onMouseDown={() => {
        if (!busy) onClose()
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-t-xl border border-vault-border bg-vault-card shadow-2xl sm:rounded-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-vault-border px-5 py-4">
          <h2 className="font-semibold text-vault-text">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t('common.close')}
            className="rounded p-1 text-vault-text-muted hover:bg-vault-card-hover disabled:opacity-50"
          >
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  )
}

const SECONDARY_BUTTON =
  'rounded-md border border-vault-border px-4 py-2 text-sm text-vault-text-secondary hover:bg-vault-card-hover disabled:opacity-50'
const PRIMARY_BUTTON =
  'rounded-md bg-vault-accent px-4 py-2 text-sm font-medium text-white hover:bg-vault-accent/90 disabled:opacity-50'

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
    <DialogShell title={t('queue.subscribedTitle')} busy={busy} onClose={onClose}>
      <div className="space-y-2 p-5 text-sm text-vault-text-secondary" data-testid="subscribed-dialog">
        <p>{t('queue.subscribedBody', { name })}</p>
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button
          type="button"
          data-testid="subscribed-download-anyway"
          onClick={onDownloadAnyway}
          disabled={busy}
          className={SECONDARY_BUTTON}
        >
          {t('queue.downloadAnyway')}
        </button>
        {canCheck && (
          <button
            type="button"
            autoFocus
            data-testid="subscribed-check-now"
            onClick={onCheck}
            disabled={busy}
            className={PRIMARY_BUTTON}
          >
            {t('queue.checkSubscriptionNow')}
          </button>
        )}
      </footer>
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
    <DialogShell title={t('library.repairDialogTitle')} busy={busy} onClose={onClose}>
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
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <button type="button" onClick={onClose} disabled={busy} className={SECONDARY_BUTTON}>
          {t('common.cancel')}
        </button>
        <button
          type="button"
          autoFocus
          data-testid="repair-confirm"
          onClick={() => onConfirm(includeExcluded)}
          disabled={busy}
          className={PRIMARY_BUTTON}
        >
          {t('library.repairStart')}
        </button>
      </footer>
    </DialogShell>
  )
}
