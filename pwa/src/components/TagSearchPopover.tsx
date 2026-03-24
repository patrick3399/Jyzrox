'use client'

import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useRouter } from 'next/navigation'
import { t } from '@/lib/i18n'

interface TagSearchPopoverProps {
  tag: string // "namespace:name" format, or bare name for general tags
  gallerySource: string // "ehentai" | "pixiv" | "local" | other
  anchorEl: HTMLElement
  onClose: () => void
}

export function TagSearchPopover({ tag, gallerySource, anchorEl, onClose }: TagSearchPopoverProps) {
  const router = useRouter()
  const popoverRef = useRef<HTMLDivElement | undefined>(undefined)

  // Compute the bare name part (strip namespace if present)
  const name = tag.includes(':') ? tag.split(':').slice(1).join(':') : tag

  const rect = anchorEl.getBoundingClientRect()
  const top = rect.bottom + window.scrollY + 4
  const left = rect.left + window.scrollX

  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  const handleSearchLocal = () => {
    onClose()
    router.push(`/library?q=${encodeURIComponent(name)}`)
  }

  const handleSearchEhentai = () => {
    onClose()
    router.push(`/e-hentai?q=${encodeURIComponent(tag)}`)
  }

  const handleSearchPixiv = () => {
    onClose()
    router.push(`/pixiv?tab=search&q=${encodeURIComponent(name)}`)
  }

  const content = (
    <div
      ref={(el) => {
        popoverRef.current = el ?? undefined
      }}
      style={{ position: 'absolute', top, left, zIndex: 9999 }}
      className="min-w-[180px] bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden"
    >
      <button
        onClick={handleSearchLocal}
        className="w-full text-left px-3 py-2 text-sm text-vault-text hover:bg-vault-hover transition-colors"
      >
        {t('tags.searchLocal')}
      </button>
      {gallerySource === 'ehentai' && (
        <button
          onClick={handleSearchEhentai}
          className="w-full text-left px-3 py-2 text-sm text-vault-text hover:bg-vault-hover transition-colors border-t border-vault-border"
        >
          {t('tags.searchEhentai')}
        </button>
      )}
      {gallerySource === 'pixiv' && (
        <button
          onClick={handleSearchPixiv}
          className="w-full text-left px-3 py-2 text-sm text-vault-text hover:bg-vault-hover transition-colors border-t border-vault-border"
        >
          {t('tags.searchPixiv')}
        </button>
      )}
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}
