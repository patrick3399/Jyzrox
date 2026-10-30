'use client'

import type { ReactNode } from 'react'
import { Popover as BasePopover } from '@base-ui/react/popover'
import { cn } from '@/lib/cn'
import { overlayOpenChange } from './overlay'

export const floatingPopupClass =
  'origin-(--transform-origin) rounded-lg border border-vault-border bg-vault-card text-vault-text shadow-vault-popup outline-none transition-[transform,opacity] duration-(--motion-fast) ease-vault-out data-[starting-style]:scale-95 data-[starting-style]:opacity-0 data-[ending-style]:scale-95 data-[ending-style]:opacity-0'

interface PopoverProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  anchor: Element | null
  children: ReactNode
  side?: 'top' | 'bottom'
  align?: 'start' | 'center' | 'end'
  ariaLabel?: string
  className?: string
}

export function Popover({ open, onOpenChange, anchor, children, side = 'bottom', align = 'start', ariaLabel, className }: PopoverProps) {
  return (
    <BasePopover.Root open={open} onOpenChange={overlayOpenChange(onOpenChange)}>
      <BasePopover.Portal>
        <BasePopover.Positioner anchor={anchor} side={side} align={align} sideOffset={4} collisionPadding={8} className="z-[110]">
          <BasePopover.Popup aria-label={ariaLabel} className={cn(floatingPopupClass, className)}>
            {children}
          </BasePopover.Popup>
        </BasePopover.Positioner>
      </BasePopover.Portal>
    </BasePopover.Root>
  )
}
