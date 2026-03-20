'use client'

import { useCallback, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  BookOpen,
  ExternalLink,
  Heart,
  Download,
  Check,
  Trash2,
  Bookmark,
  BookmarkCheck,
} from 'lucide-react'
import type { Gallery } from '@/lib/types'
import { RatingStars } from '@/components/RatingStars'
import { ContextMenu } from '@/components/ContextMenu'
import { useLongPress } from '@/hooks/useLongPress'
import { getSourceStyle, getEventPosition } from '@/lib/galleryUtils'
import { t } from '@/lib/i18n'

// ── Props ─────────────────────────────────────────────────────────────

interface GalleryListCardProps {
  gallery: Gallery
  thumbUrl?: string
  onClick?: () => void
  selected?: boolean
  selectMode?: boolean
  onFavoriteToggle?: (gallery: Gallery) => void
  onReadingListToggle?: (gallery: Gallery) => void
  onDelete?: (gallery: Gallery) => void
  onDownload?: (gallery: Gallery) => void
}

// ── Component ─────────────────────────────────────────────────────────

export function GalleryListCard({
  gallery,
  thumbUrl,
  onClick,
  selected,
  selectMode,
  onFavoriteToggle,
  onReadingListToggle,
  onDelete,
  onDownload,
}: GalleryListCardProps) {
  const router = useRouter()
  const sourceStyle = getSourceStyle(gallery)

  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPos, setMenuPos] = useState({ x: 0, y: 0 })

  const handleLongPress = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    e.preventDefault()
    const pos = getEventPosition(e)
    setMenuPos(pos)
    setMenuOpen(true)
  }, [])

  const longPressHandlers = useLongPress({ onLongPress: handleLongPress })

  const contextItems = [
    {
      label: t('contextMenu.read'),
      icon: BookOpen,
      onClick: () => router.push(`/reader/${gallery.source}/${gallery.source_id}`),
    },
    {
      label: t('contextMenu.openDetail'),
      icon: ExternalLink,
      onClick: () => router.push(`/library/${gallery.source}/${gallery.source_id}`),
    },
    ...(onFavoriteToggle
      ? [
          {
            label: gallery.is_favorited ? t('contextMenu.unfavorite') : t('contextMenu.favorite'),
            icon: Heart,
            onClick: () => onFavoriteToggle(gallery),
          },
        ]
      : []),
    ...(onReadingListToggle
      ? [
          {
            label: gallery.in_reading_list
              ? t('contextMenu.removeFromReadingList')
              : t('contextMenu.addToReadingList'),
            icon: gallery.in_reading_list ? BookmarkCheck : Bookmark,
            onClick: () => onReadingListToggle(gallery),
          },
        ]
      : []),
    ...(onDownload
      ? [
          {
            label: t('contextMenu.download'),
            icon: Download,
            onClick: () => onDownload(gallery),
          },
        ]
      : []),
    ...(onDelete
      ? [
          {
            label: t('contextMenu.delete'),
            icon: Trash2,
            className: 'text-red-400',
            onClick: () => onDelete(gallery),
          },
        ]
      : []),
  ]

  // Up to 5 tags shown inline, rest truncated
  const visibleTags = gallery.tags_array.slice(0, 5)
  const extraTagCount = gallery.tags_array.length - visibleTags.length

  return (
    <>
      <article
        onClick={onClick}
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
        onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
        {...longPressHandlers}
        className={`
          relative flex gap-3 p-3 select-none [-webkit-touch-callout:none]
          bg-vault-card rounded-lg overflow-hidden
          transition-all duration-150 cursor-pointer
          hover:bg-vault-card-hover hover:border-vault-accent
          focus:outline-none focus:ring-2 focus:ring-vault-accent
          ${selected || menuOpen ? 'border-2 border-vault-accent' : 'border border-vault-border'}
        `}
      >
        {/* Select-mode checkbox overlay */}
        {selectMode && (
          <div className="absolute top-2 left-2 z-10">
            <div
              className={`w-5 h-5 rounded border-2 flex items-center justify-center ${
                selected
                  ? 'bg-vault-accent border-vault-accent text-white'
                  : 'border-white/60 bg-black/30'
              }`}
            >
              {selected && <Check size={12} />}
            </div>
          </div>
        )}

        {/* Thumbnail */}
        <div className="shrink-0 w-[88px] h-[118px] rounded overflow-hidden bg-vault-input">
          {thumbUrl ? (
            <img
              src={thumbUrl}
              alt={gallery.title}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-vault-input">
              <span className="text-xs text-vault-text-muted uppercase tracking-wider">
                {gallery.category || t('library.categoryUncategorized')}
              </span>
            </div>
          )}
        </div>

        {/* Metadata column */}
        <div className="flex flex-col flex-1 min-w-0 gap-1">
          {/* Title */}
          <h3 className="text-sm font-medium text-vault-text line-clamp-2 leading-snug">
            {gallery.title || gallery.title_jpn}
          </h3>

          {/* Secondary title */}
          {gallery.title_jpn && gallery.title && (
            <p className="text-xs text-vault-text-muted line-clamp-1">{gallery.title_jpn}</p>
          )}

          {/* Tags summary */}
          {visibleTags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-0.5">
              {visibleTags.map((tag) => (
                <span
                  key={tag}
                  className="px-1.5 py-0.5 rounded text-[10px] bg-vault-input text-vault-text-muted border border-vault-border truncate max-w-[120px]"
                >
                  {tag}
                </span>
              ))}
              {extraTagCount > 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] text-vault-text-muted">
                  +{extraTagCount}
                </span>
              )}
            </div>
          )}

          {/* Bottom meta row */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-auto pt-1">
            {/* Source badge */}
            <span
              className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-medium ${sourceStyle.className}`}
            >
              {sourceStyle.label}
            </span>

            {/* Rating */}
            <RatingStars rating={gallery.my_rating ?? gallery.rating} readonly />

            {/* Pages */}
            <span className="text-xs text-vault-text-muted ml-auto">{gallery.pages}p</span>

            {/* Favourite indicator */}
            {gallery.is_favorited && (
              <span
                className="text-red-400 text-sm leading-none"
                aria-label={t('common.favourited')}
              >
                ♥
              </span>
            )}

            {/* Downloading indicator */}
            {gallery.download_status === 'downloading' && !selectMode && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-600/90 text-white text-[10px] font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                {t('queue.downloading')}
              </span>
            )}
          </div>
        </div>
      </article>

      <ContextMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        position={menuPos}
        items={contextItems}
      />
    </>
  )
}
