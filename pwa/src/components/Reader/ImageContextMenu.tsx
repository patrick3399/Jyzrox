'use client'

import { useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Download, Copy, Share2, EyeOff, Heart, type LucideIcon } from 'lucide-react'
import { t } from '@/lib/i18n'

interface ImageContextMenuProps {
  open: boolean
  onClose: () => void
  position: { x: number; y: number }
  imageUrl: string
  imageName?: string
  onHide?: () => void
  isFavorited?: boolean
  onToggleFavorite?: () => void
}

export function ImageContextMenu({ open, onClose, position, imageUrl, imageName, onHide, isFavorited, onToggleFavorite }: ImageContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // ── Phantom-click guard ──────────────────────────────────────────────
  // On mobile, after a long-press the browser generates a synthetic click
  // at the finger coordinates.  Because the context menu portal renders
  // directly under the finger, the Favorite button receives a click that
  // was never preceded by a pointerdown on the menu.  A *real* tap always
  // produces pointerdown → click on the same element.  We exploit this:
  // set a flag on pointerdown inside the menu, and only honour onClick
  // when the flag is set.  Reset it on every click so it's one-shot.
  const hadPointerDownRef = useRef(false)

  const handleMenuPointerDown = useCallback(() => {
    hadPointerDownRef.current = true
  }, [])

  // Wraps every item action: only fires if preceded by a real pointerdown.
  const guardedClick = useCallback((action: () => void) => {
    return (e: React.MouseEvent) => {
      e.stopPropagation()
      if (!hadPointerDownRef.current) return   // phantom click — ignore
      hadPointerDownRef.current = false
      action()
    }
  }, [])

  // Reset guard whenever the menu opens/closes.
  useEffect(() => {
    hadPointerDownRef.current = false
  }, [open])

  // ── Dismiss on outside-click or Escape ───────────────────────────────
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() },
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

  // 1. Save Image — download the image
  const handleSave = () => {
    const a = document.createElement('a')
    a.href = imageUrl
    a.download = imageName || 'image'
    a.click()
    onClose()
  }

  // 2. Copy Image — use clipboard API
  const handleCopy = async () => {
    try {
      const response = await fetch(imageUrl)
      const blob = await response.blob()
      await navigator.clipboard.write([
        new ClipboardItem({ [blob.type]: blob }),
      ])
    } catch {
      // Fallback: copy URL instead
      await navigator.clipboard.writeText(imageUrl)
    }
    onClose()
  }

  // 3. Share — use Web Share API
  const handleShare = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ url: imageUrl })
      } catch {
        // User cancelled or share failed
      }
    }
    onClose()
  }

  if (!open) return null

  // Viewport boundary detection to prevent going off-screen
  const MENU_WIDTH = 200
  const ITEM_HEIGHT = 48
  const SEPARATOR_HEIGHT = 1
  const hasShare = typeof navigator !== 'undefined' && !!navigator.share
  const baseItems = (hasShare ? 3 : 2) + (onToggleFavorite ? 1 : 0)
  const MENU_HEIGHT = baseItems * ITEM_HEIGHT + (onHide ? SEPARATOR_HEIGHT + ITEM_HEIGHT : 0)

  const x = Math.min(position.x, window.innerWidth - MENU_WIDTH - 8)
  const y = Math.min(position.y, window.innerHeight - MENU_HEIGHT - 8)
  const adjustedX = Math.max(8, x)
  const adjustedY = Math.max(8, y)

  const items: { label: string; icon: LucideIcon; onClick: () => void; iconClassName?: string }[] = [
    ...(onToggleFavorite ? [{
      label: isFavorited ? t('reader.unfavoriteImage') : t('reader.favoriteImage'),
      icon: Heart,
      onClick: () => { onToggleFavorite(); onClose() },
      iconClassName: isFavorited ? 'fill-current text-red-400' : 'text-white/70',
    }] : []),
    { label: t('reader.saveImage'), icon: Download, onClick: handleSave },
    { label: t('reader.copyImage'), icon: Copy, onClick: handleCopy },
    ...(hasShare ? [{ label: t('reader.shareImage'), icon: Share2, onClick: handleShare }] : []),
  ]

  const menu = (
    <>
      {/* Invisible full-screen backdrop to catch outside clicks */}
      <div
        className="fixed inset-0 z-[199]"
        aria-hidden="true"
        onPointerDown={(e) => { e.stopPropagation(); onClose() }}
        onContextMenu={(e) => { e.preventDefault(); onClose() }}
      />
      <div
        ref={menuRef}
        role="menu"
        aria-label="Image context menu"
        tabIndex={-1}
        className="fixed z-[200] bg-neutral-900/95 backdrop-blur-sm border border-white/10 rounded-xl shadow-2xl overflow-hidden outline-none"
        style={{ left: adjustedX, top: adjustedY, width: MENU_WIDTH }}
        onPointerDown={handleMenuPointerDown}
        onClick={(e) => e.stopPropagation()}
      >
        {items.map(({ label, icon: Icon, onClick, iconClassName }) => (
          <button
            key={label}
            role="menuitem"
            onClick={guardedClick(onClick)}
            className="w-full px-4 py-3 text-sm text-white/90 hover:bg-white/10 flex items-center gap-3 transition-colors text-left"
          >
            <Icon className={`w-4 h-4 shrink-0 ${iconClassName || 'text-white/70'}`} />
            <span>{label}</span>
          </button>
        ))}
        {onHide && (
          <>
            <div className="border-t border-white/10" />
            <button
              role="menuitem"
              onClick={guardedClick(() => { onHide(); onClose() })}
              className="w-full px-4 py-3 text-sm text-red-400 hover:bg-white/10 flex items-center gap-3 transition-colors text-left"
            >
              <EyeOff className="w-4 h-4 shrink-0 text-red-400/70" />
              <span>{t('reader.hideImage')}</span>
            </button>
          </>
        )}
      </div>
    </>
  )

  return createPortal(menu, document.body)
}
