'use client'

import type { ReactNode, RefObject } from 'react'
import { Dialog as BaseDialog } from '@base-ui/react/dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { t } from '@/lib/i18n'
import { Button } from './button'
import { overlayOpenChange } from './overlay'

export const overlayBackdropClass =
  'fixed inset-0 z-[100] bg-vault-overlay transition-opacity duration-(--motion-base) ease-vault-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0'

/** Bottom sheet below `sm`, centred card from `sm`. */
export const sheetPopupClass =
  'flex max-h-[90dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-vault-border bg-vault-card pb-(--sab) text-vault-text shadow-vault-popup outline-none transition-[transform,opacity] duration-(--motion-base) ease-vault-out data-[starting-style]:translate-y-full data-[ending-style]:translate-y-full sm:rounded-xl sm:pb-0 sm:data-[starting-style]:translate-y-0 sm:data-[starting-style]:scale-95 sm:data-[starting-style]:opacity-0 sm:data-[ending-style]:translate-y-0 sm:data-[ending-style]:scale-95 sm:data-[ending-style]:opacity-0'

const SIZE = { sm: 'sm:max-w-sm', md: 'sm:max-w-md', lg: 'sm:max-w-xl', xl: 'sm:max-w-3xl' } as const

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: keyof typeof SIZE
  /** false while a request is in flight: Escape, backdrop and ✕ do nothing. */
  dismissible?: boolean
  /** false for edge-to-edge bodies such as action lists. */
  padded?: boolean
  className?: string
  /** Element to focus on open (defaults to the first tabbable). */
  initialFocus?: RefObject<HTMLElement | null>
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
  dismissible = true,
  padded = true,
  className,
  initialFocus,
}: DialogProps) {
  return (
    <BaseDialog.Root open={open} onOpenChange={overlayOpenChange(onOpenChange, dismissible)}>
      <BaseDialog.Portal>
        <BaseDialog.Backdrop className={overlayBackdropClass} />
        <BaseDialog.Viewport className="fixed inset-0 z-[100] flex items-end justify-center sm:items-center sm:p-4">
          <BaseDialog.Popup className={cn(sheetPopupClass, SIZE[size], className)} initialFocus={initialFocus}>
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-vault-border px-5 py-3">
              <BaseDialog.Title className="min-w-0 truncate font-semibold">{title}</BaseDialog.Title>
              <BaseDialog.Close
                render={<Button variant="ghost" size="icon" aria-label={t('common.close')} disabled={!dismissible} />}
              >
                <X size={18} />
              </BaseDialog.Close>
            </header>
            {description && (
              <BaseDialog.Description className="px-5 pt-3 text-sm text-vault-text-secondary">{description}</BaseDialog.Description>
            )}
            <div className={cn('min-h-0 flex-1 overflow-y-auto', padded && 'px-5 py-4')}>{children}</div>
            {footer && (
              <footer className="flex shrink-0 justify-end gap-2 border-t border-vault-border px-5 py-3">{footer}</footer>
            )}
          </BaseDialog.Popup>
        </BaseDialog.Viewport>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  )
}
