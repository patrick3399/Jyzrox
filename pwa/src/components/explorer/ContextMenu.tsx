'use client'

import { useEffect } from 'react'
import { AnchoredMenu, type MenuEntry } from '@/components/ui/menu'

export type ContextMenuEntry = MenuEntry

interface ContextMenuProps {
  x: number
  y: number
  items: ContextMenuEntry[]
  ariaLabel: string
  onClose: () => void
}

/**
 * Right-click menu rendered by AnchoredMenu (portalled by Base UI, so the
 * Workbench CSS containment does not offset it). Base UI handles Escape,
 * outside press, focus return and arrow keys; scroll, wheel, resize and window
 * blur are closed here.
 */
export function ContextMenu({ x, y, items, ariaLabel, onClose }: ContextMenuProps) {
  useEffect(() => {
    const close = () => onClose()
    window.addEventListener('scroll', close, true)
    window.addEventListener('wheel', close, { passive: true })
    window.addEventListener('resize', close)
    window.addEventListener('blur', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('wheel', close)
      window.removeEventListener('resize', close)
      window.removeEventListener('blur', close)
    }
  }, [onClose])

  return (
    <AnchoredMenu
      open
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
      x={x}
      y={y}
      ariaLabel={ariaLabel}
      items={items}
    />
  )
}
