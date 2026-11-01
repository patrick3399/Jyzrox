'use client'

import { useRouter } from 'next/navigation'
import { Popover } from '@/components/ui/popover'
import { t } from '@/lib/i18n'
import { tagNameSearchTerm } from '@/lib/queryParser'

interface TagSearchPopoverProps {
  tag: string // "namespace:name" format, or bare name for general tags
  gallerySource: string // "ehentai" | "pixiv" | "local" | other
  anchorEl: HTMLElement
  onClose: () => void
}

export function TagSearchPopover({ tag, gallerySource, anchorEl, onClose }: TagSearchPopoverProps) {
  const router = useRouter()
  // Compute the bare name part (strip namespace if present)
  const name = tag.includes(':') ? tag.split(':').slice(1).join(':') : tag

  const handleSearchLocal = () => {
    onClose()
    router.push(`/library?q=${encodeURIComponent(tagNameSearchTerm(name))}`)
  }

  const handleSearchEhentai = () => {
    onClose()
    router.push(`/e-hentai?q=${encodeURIComponent(tag)}`)
  }

  const handleSearchPixiv = () => {
    onClose()
    router.push(`/pixiv?tab=search&q=${encodeURIComponent(name)}`)
  }

  return (
    <Popover
      open
      anchor={anchorEl}
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
      className="min-w-[180px] overflow-hidden"
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
    </Popover>
  )
}
