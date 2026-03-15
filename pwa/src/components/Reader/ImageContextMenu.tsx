'use client'

import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Download, Copy, Share2, EyeOff } from 'lucide-react'
import { t } from '@/lib/i18n'

interface ImageContextMenuProps {
  open: boolean
  onClose: () => void
  position: { x: number; y: number }
  imageUrl: string
  imageName?: string
  onHide?: () => void
}

export function ImageContextMenu({ open, onClose, position, imageUrl, imageName, onHide }: ImageContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Auto-dismiss on click outside or Escape
  useEffect(() => {
    if (!open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }

    const handlePointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    // Use capture so we get the event before anything else
    document.addEventListener('pointerdown', handlePointerDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('pointerdown', handlePointerDown, true)
    }
  }, [open, onClose])

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
  const baseItems = hasShare ? 3 : 2
  const MENU_HEIGHT = baseItems * ITEM_HEIGHT + (onHide ? SEPARATOR_HEIGHT + ITEM_HEIGHT : 0)

  const x = Math.min(position.x, window.innerWidth - MENU_WIDTH - 8)
  const y = Math.min(position.y, window.innerHeight - MENU_HEIGHT - 8)
  const adjustedX = Math.max(8, x)
  const adjustedY = Math.max(8, y)

  const items = [
    { label: t('reader.saveImage'), icon: Download, onClick: handleSave },
    { label: t('reader.copyImage'), icon: Copy, onClick: handleCopy },
    ...(hasShare ? [{ label: t('reader.shareImage'), icon: Share2, onClick: handleShare }] : []),
  ]

  const menu = (
    <>
      {/* Invisible full-screen backdrop to catch outside clicks */}
      <div
        className="fixed inset-0 z-[199]"
        onClick={onClose}
        onContextMenu={(e) => { e.preventDefault(); onClose() }}
      />
      <div
        ref={menuRef}
        className="fixed z-[200] bg-neutral-900/95 backdrop-blur-sm border border-white/10 rounded-xl shadow-2xl overflow-hidden"
        style={{ left: adjustedX, top: adjustedY, width: MENU_WIDTH }}
        onClick={(e) => e.stopPropagation()}
      >
        {items.map(({ label, icon: Icon, onClick }) => (
          <button
            key={label}
            onClick={onClick}
            className="w-full px-4 py-3 text-sm text-white/90 hover:bg-white/10 flex items-center gap-3 transition-colors text-left"
          >
            <Icon className="w-4 h-4 shrink-0 text-white/70" />
            <span>{label}</span>
          </button>
        ))}
        {onHide && (
          <>
            <div className="border-t border-white/10" />
            <button
              onClick={onHide}
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
