'use client'

import type { ReactNode } from 'react'
import { AlertDialog as BaseAlertDialog } from '@base-ui/react/alert-dialog'
import { cn } from '@/lib/cn'
import { t } from '@/lib/i18n'
import { Button } from './button'
import { overlayBackdropClass, sheetPopupClass } from './dialog'
import { overlayOpenChange } from './overlay'

interface AlertDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  confirmLabel: string
  onConfirm: () => void
  destructive?: boolean
  busy?: boolean
}

export function AlertDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  destructive = false,
  busy = false,
}: AlertDialogProps) {
  return (
    <BaseAlertDialog.Root open={open} onOpenChange={overlayOpenChange(onOpenChange, !busy)}>
      <BaseAlertDialog.Portal>
        <BaseAlertDialog.Backdrop className={overlayBackdropClass} />
        <BaseAlertDialog.Viewport className="fixed inset-0 z-[100] flex items-end justify-center sm:items-center sm:p-4">
          <BaseAlertDialog.Popup className={cn(sheetPopupClass, 'sm:max-w-sm')}>
            <div className="space-y-2 px-5 pt-5">
              <BaseAlertDialog.Title className="font-semibold">{title}</BaseAlertDialog.Title>
              {description && (
                <BaseAlertDialog.Description className="text-sm text-vault-text-secondary">{description}</BaseAlertDialog.Description>
              )}
            </div>
            <div className="flex justify-end gap-2 px-5 py-4">
              <BaseAlertDialog.Close render={<Button disabled={busy} />}>{t('common.cancel')}</BaseAlertDialog.Close>
              <Button variant={destructive ? 'danger' : 'primary'} disabled={busy} onClick={onConfirm}>
                {confirmLabel}
              </Button>
            </div>
          </BaseAlertDialog.Popup>
        </BaseAlertDialog.Viewport>
      </BaseAlertDialog.Portal>
    </BaseAlertDialog.Root>
  )
}
