'use client'

import { useEffect, useLayoutEffect, useRef, useState, type ComponentType } from 'react'
import { createPortal } from 'react-dom'

export interface ContextMenuEntry {
  id: string
  label: string
  icon?: ComponentType<{ size?: number; className?: string }>
  danger?: boolean
  disabled?: boolean
  /** Draw a divider above this entry. */
  separator?: boolean
  onSelect: () => void
}

interface ContextMenuProps {
  x: number
  y: number
  items: ContextMenuEntry[]
  ariaLabel: string
  onClose: () => void
}

const VIEWPORT_MARGIN = 8

/**
 * Right-click menu. Portaled to <body> because the Workbench root uses CSS
 * containment, which would otherwise offset `position: fixed` children.
 * Closes on Escape, outside pointer press, scroll, resize, and window blur.
 */
export function ContextMenu({ x, y, items, ariaLabel, onClose }: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [position, setPosition] = useState({ left: x, top: y })
  const returnFocusRef = useRef<HTMLElement | null>(null)

  useLayoutEffect(() => {
    const menu = menuRef.current
    if (!menu) return
    const { offsetWidth: width, offsetHeight: height } = menu
    const maxLeft = window.innerWidth - width - VIEWPORT_MARGIN
    const maxTop = window.innerHeight - height - VIEWPORT_MARGIN
    setPosition({
      left: Math.max(VIEWPORT_MARGIN, Math.min(x, maxLeft)),
      top: Math.max(VIEWPORT_MARGIN, Math.min(y, maxTop)),
    })
  }, [x, y, items.length])

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    menuRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
  }, [])

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return
      onClose()
    }
    const close = () => onClose()
    document.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('scroll', close, true)
    window.addEventListener('wheel', close, { passive: true })
    window.addEventListener('resize', close)
    window.addEventListener('blur', close)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('wheel', close)
      window.removeEventListener('resize', close)
      window.removeEventListener('blur', close)
    }
  }, [onClose])

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      returnFocusRef.current?.focus({ preventScroll: true })
      onClose()
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      onClose()
      return
    }
    const buttons = [...(menuRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])]
    if (buttons.length === 0) return
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
    let next: number | null = null
    if (event.key === 'ArrowDown') next = current < 0 ? 0 : (current + 1) % buttons.length
    else if (event.key === 'ArrowUp') next = current <= 0 ? buttons.length - 1 : current - 1
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = buttons.length - 1
    if (next === null) return
    event.preventDefault()
    event.stopPropagation()
    buttons[next]?.focus()
  }

  if (typeof document === 'undefined') return null
  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-label={ariaLabel}
      data-testid="explorer-context-menu"
      onKeyDown={handleKeyDown}
      onContextMenu={(event) => event.preventDefault()}
      style={{ left: position.left, top: position.top }}
      className="fixed z-[120] min-w-[190px] overflow-hidden rounded-lg border border-vault-border bg-vault-card py-1 shadow-2xl"
    >
      {items.map((item) => {
        const Icon = item.icon
        return (
          <div key={item.id} role="none">
            {item.separator && <div role="separator" className="my-1 border-t border-vault-border" />}
            <button
              type="button"
              role="menuitem"
              disabled={item.disabled}
              data-testid={`context-menu-${item.id}`}
              onClick={() => {
                onClose()
                item.onSelect()
              }}
              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm outline-none transition-colors disabled:opacity-40 ${
                item.danger ? 'text-red-400 hover:bg-red-500/10 focus:bg-red-500/10' : 'text-vault-text hover:bg-vault-card-hover focus:bg-vault-card-hover'
              }`}
            >
              {Icon && <Icon size={15} className="shrink-0" />}
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
            </button>
          </div>
        )
      })}
    </div>,
    document.body,
  )
}
