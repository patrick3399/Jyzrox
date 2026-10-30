'use client'

import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { t } from '@/lib/i18n'

interface LibraryFilterSheetProps {
  open: boolean
  onClose: () => void
  children: ReactNode
}

/** Filter controls: bottom sheet on small screens, centered dialog from `sm`. */
export function LibraryFilterSheet({ open, onClose, children }: LibraryFilterSheetProps) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={t('library.filters')}
        className="w-full sm:w-96 sm:max-w-[90vw] max-h-[85vh] flex flex-col bg-vault-card border border-vault-border rounded-t-xl sm:rounded-lg pb-[var(--sab)] sm:pb-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-vault-border">
          <h3 className="text-base font-medium text-vault-text">{t('library.filters')}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="p-2 -m-2 text-vault-text-muted hover:text-vault-text"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-4">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
