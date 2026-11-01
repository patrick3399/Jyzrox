'use client'

import { Fragment, useMemo, type ComponentType } from 'react'
import { Menu } from '@base-ui/react/menu'
import { cn } from '@/lib/cn'
import { overlayOpenChange } from './overlay'
import { floatingPopupClass } from './popover'

export interface MenuEntry {
  id: string
  label: string
  icon?: ComponentType<{ size?: number; className?: string }>
  danger?: boolean
  disabled?: boolean
  /** Draw a divider above this entry. */
  separator?: boolean
  onSelect: () => void
}

interface AnchoredMenuProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Viewport coordinates (clientX/clientY) of the press. */
  x: number
  y: number
  ariaLabel: string
  items: MenuEntry[]
}

export function AnchoredMenu({ open, onOpenChange, x, y, ariaLabel, items }: AnchoredMenuProps) {
  const anchor = useMemo(() => ({ getBoundingClientRect: () => DOMRect.fromRect({ x, y, width: 0, height: 0 }) }), [x, y])
  return (
    <Menu.Root open={open} onOpenChange={overlayOpenChange(onOpenChange)}>
      <Menu.Portal>
        <Menu.Positioner anchor={anchor} side="bottom" align="start" collisionPadding={8} className="z-[110]">
          {/* Right-clicking inside an open context menu must not open the browser's native menu on top of it. */}
          <Menu.Popup
            aria-label={ariaLabel}
            className={cn(floatingPopupClass, 'min-w-44 py-1')}
            onContextMenu={(event) => event.preventDefault()}
          >
            {items.map((item) => {
              const Icon = item.icon
              return (
                <Fragment key={item.id}>
                  {item.separator && <Menu.Separator className="my-1 h-px bg-vault-border" />}
                  <Menu.Item
                    disabled={item.disabled}
                    onClick={item.onSelect}
                    className={cn(
                      'flex min-h-9 cursor-default items-center gap-2 px-3 text-sm outline-none data-[highlighted]:bg-vault-card-hover data-[disabled]:opacity-50',
                      item.danger ? 'text-vault-danger' : 'text-vault-text',
                    )}
                  >
                    {Icon && <Icon size={16} className="shrink-0" />}
                    <span className="truncate">{item.label}</span>
                  </Menu.Item>
                </Fragment>
              )
            })}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  )
}
