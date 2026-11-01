'use client'

import Link from 'next/link'
import type { LucideIcon } from 'lucide-react'
import { t } from '@/lib/i18n'
import { Dialog } from '@/components/ui/dialog'

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

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      title={t('library.moreActions')}
      size="sm"
      padded={false}
    >
      {visibleGroups.map((group, index) => (
        <ul key={group[0].id} className={index > 0 ? 'border-t border-vault-border' : ''}>
          {group.map((action) => (
            <li key={action.id}>{renderAction(action)}</li>
          ))}
        </ul>
      ))}
    </Dialog>
  )
}
