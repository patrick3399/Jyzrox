'use client'
import { useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import type { LucideIcon } from 'lucide-react'

export interface ContextMenuItem {
  label: string
  icon?: LucideIcon
  className?: string
  onClick: () => void
}

interface ContextMenuProps {
  open: boolean
  onClose: () => void
  position: { x: number; y: number }
  items: ContextMenuItem[]
}

const MENU_WIDTH = 180
const MENU_ITEM_HEIGHT = 36
const MENU_PADDING = 8

export function ContextMenu({ open, onClose, position, items }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose],
  )

  useEffect(() => {
    if (!open) return
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, handleKeyDown])

  // Focus the menu container when it opens so keyboard users can interact.
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => menuRef.current?.focus())
    }
  }, [open])

  if (!open || typeof window === 'undefined') return null

  // Viewport boundary detection — flip if the menu would overflow.
  const estimatedHeight = items.length * MENU_ITEM_HEIGHT + MENU_PADDING * 2
  const vw = window.innerWidth
  const vh = window.innerHeight

  let x = position.x
  let y = position.y

  if (x + MENU_WIDTH > vw - 8) x = vw - MENU_WIDTH - 8
  if (x < 8) x = 8
  if (y + estimatedHeight > vh - 8) y = Math.max(8, y - estimatedHeight)

  return createPortal(
    <>
      {/* Invisible backdrop to catch outside-click */}
      <div
        className="fixed inset-0 z-[9998]"
        aria-hidden="true"
        onPointerDown={(e) => { e.stopPropagation(); onClose() }}
      />

      <div
        ref={menuRef}
        role="menu"
        aria-label="Context menu"
        tabIndex={-1}
        className="fixed z-[9999] min-w-[180px] bg-vault-card border border-vault-border rounded-lg shadow-xl py-1 outline-none"
        style={{ left: x, top: y }}
      >
        {items.map((item, idx) => {
          const Icon = item.icon
          return (
            <button
              key={idx}
              role="menuitem"
              className={`flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-vault-card-hover focus:bg-vault-card-hover outline-none transition-colors duration-100 ${item.className ?? 'text-vault-text'}`}
              onClick={(e) => {
                e.stopPropagation()
                item.onClick()
                onClose()
              }}
            >
              {Icon && <Icon size={15} className={`shrink-0 ${item.className ?? 'text-vault-text-muted'}`} />}
              {item.label}
            </button>
          )
        })}
      </div>
    </>,
    document.body,
  )
}
