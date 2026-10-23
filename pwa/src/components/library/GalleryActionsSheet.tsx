'use client'

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { X, type LucideIcon } from 'lucide-react'
import { t } from '@/lib/i18n'

export interface GalleryAction {
  id: string
  label: string
  icon: LucideIcon
  /** Navigation target; rendered as a link instead of a button. */
  href?: string
  /** Open `href` in a new tab instead of client-side navigation. */
  external?: boolean
  onSelect?: () => void
  danger?: boolean
  disabled?: boolean
}

interface GalleryActionsSheetProps {
  open: boolean
  onClose: () => void
  /** Groups are separated by a divider; empty groups are dropped. */
  groups: GalleryAction[][]
}

const ROW_CLASS =
  'w-full flex items-center gap-3 px-4 py-3 min-h-11 text-left text-sm transition-colors hover:bg-vault-hover active:bg-vault-hover disabled:opacity-50'

/**
 * Low-frequency gallery actions, kept out of the detail header so it stays
 * short on phones. Bottom sheet on small screens, centered dialog from `sm`
 * (same shape as AddToCollectionMenu).
 */
export function GalleryActionsSheet({ open, onClose, groups }: GalleryActionsSheetProps) {
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // The detail page binds Escape on window to "go back"; this runs first
      // (document bubbles before window), so stop it from closing the page too.
      e.stopPropagation()
      onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open || typeof document === 'undefined') return null

  const visibleGroups = groups.filter((group) => group.length > 0)

  const renderAction = (action: GalleryAction) => {
    const Icon = action.icon
    const className = `${ROW_CLASS} ${action.danger ? 'text-red-400' : 'text-vault-text'}`
    const content = (
      <>
        <Icon size={18} className="shrink-0" />
        <span className="flex-1 min-w-0 truncate">{action.label}</span>
      </>
    )
    if (action.href) {
      return action.external ? (
        <a
          href={action.href}
          target="_blank"
          rel="noopener noreferrer"
          className={className}
          onClick={onClose}
        >
          {content}
        </a>
      ) : (
        <Link href={action.href} className={className} onClick={onClose}>
          {content}
        </Link>
      )
    }
    return (
      <button
        type="button"
        className={className}
        disabled={action.disabled}
        onClick={() => {
          onClose()
          action.onSelect?.()
        }}
      >
        {content}
      </button>
    )
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={t('library.moreActions')}
        className="w-full sm:w-80 sm:max-w-[90vw] max-h-[80vh] flex flex-col bg-vault-card border border-vault-border rounded-t-xl sm:rounded-lg pb-[var(--sab)] sm:pb-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-vault-border">
          <h3 className="text-base font-medium text-vault-text">{t('library.moreActions')}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="p-2 -m-2 text-vault-text-muted hover:text-vault-text"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          {visibleGroups.map((group, index) => (
            <ul key={group[0].id} className={index > 0 ? 'border-t border-vault-border' : ''}>
              {group.map((action) => (
                <li key={action.id}>{renderAction(action)}</li>
              ))}
            </ul>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  )
}
