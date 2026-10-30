'use client'
import { useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import {
  BookOpen,
  ExternalLink,
  Heart,
  Download,
  Trash2,
  Bookmark,
  BookmarkCheck,
} from 'lucide-react'
import type { Gallery, GalleryCategoryDef } from '@/lib/types'
import { resolveCategoryColors } from '@/lib/categoryPalette'
import { ContextMenu } from './ContextMenu'
import { useLongPress } from '@/hooks/useLongPress'
import { getSourceStyle, getEventPosition } from '@/lib/galleryUtils'
import { galleryHref, readerHref } from '@/lib/galleryRoutes'
import { t } from '@/lib/i18n'
import { AppImage } from './AppImage'

// ── Category colours ──────────────────────────────────────────────────


// ── LibraryGalleryCard ────────────────────────────────────────────────

interface LibraryCardProps {
  gallery: Gallery
  categories?: GalleryCategoryDef[]
  thumbUrl?: string
  onClick?: () => void
  selected?: boolean
  selectMode?: boolean
  onFavoriteToggle?: (gallery: Gallery) => void
  onReadingListToggle?: (gallery: Gallery) => void
  onDelete?: (gallery: Gallery) => void
  onDownload?: (gallery: Gallery) => void
}

export function LibraryGalleryCard({
  gallery,
  categories,
  thumbUrl,
  onClick,
  selected,
  selectMode,
  onFavoriteToggle,
  onReadingListToggle,
  onDelete,
  onDownload,
}: LibraryCardProps) {
  const colors = resolveCategoryColors(gallery.category, categories)
  const router = useRouter()

  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPos, setMenuPos] = useState({ x: 0, y: 0 })

  const handleLongPress = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    e.preventDefault()
    setMenuPos(getEventPosition(e))
    setMenuOpen(true)
  }, [])

  const longPressHandlers = useLongPress({ onLongPress: handleLongPress })

  const sourceStyle = getSourceStyle(gallery)
  const title = gallery.title || gallery.title_jpn
  // Most library galleries are unrated: show a compact "★4" only when there is one.
  const rating = Math.round(gallery.my_rating ?? gallery.rating ?? 0)

  const contextItems = useMemo(() => {
    if (!menuOpen) return []
    return [
      {
        label: t('contextMenu.read'),
        icon: BookOpen,
        onClick: () => router.push(readerHref(gallery.source, gallery.source_id)),
      },
      {
        label: t('contextMenu.openDetail'),
        icon: ExternalLink,
        onClick: () => router.push(galleryHref(gallery.source, gallery.source_id)),
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
        ? [{ label: t('contextMenu.download'), icon: Download, onClick: () => onDownload(gallery) }]
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
  }, [menuOpen, gallery, onFavoriteToggle, onReadingListToggle, onDownload, onDelete, router])

  return (
    <>
      <article
        onClick={onClick}
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
        onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
        {...longPressHandlers}
        className={`
          relative flex flex-col select-none [-webkit-touch-callout:none]
          bg-vault-card rounded-lg overflow-hidden
          transition-all duration-200 cursor-pointer
          hover:scale-[1.02] hover:shadow-lg hover:shadow-vault-accent/20 hover:brightness-105
          focus:outline-none focus:ring-2 focus:ring-vault-accent
          ${selected || menuOpen ? 'border-2 border-vault-accent' : 'border border-vault-border hover:border-vault-accent'}
        `}
      >
        {/* Select-mode checkbox overlay */}
        {selectMode && (
          <div className="absolute top-1.5 left-1.5 z-10">
            <div
              className={`w-5 h-5 rounded border-2 flex items-center justify-center ${
                selected
                  ? 'bg-vault-accent border-vault-accent text-white'
                  : 'border-white/60 bg-black/30'
              }`}
            >
              {selected && <span className="text-xs">✓</span>}
            </div>
          </div>
        )}

        {/* Favourite indicator */}
        {gallery.is_favorited && (
          <span
            className="absolute top-1.5 right-1.5 z-10 text-red-400 text-base leading-none drop-shadow"
            aria-label={t('common.favourited')}
          >
            ♥
          </span>
        )}

        {/* Download-in-progress indicator */}
        {gallery.download_status === 'downloading' && !selectMode && (
          <div className="absolute top-1.5 left-1.5 z-10">
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-600/90 text-white text-[10px] font-medium shadow">
              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
              {t('queue.downloading')}
            </span>
          </div>
        )}

        {/* Thumbnail or gradient placeholder */}
        <div className="relative aspect-[3/4] overflow-hidden">
          {thumbUrl ? (
            <AppImage
              src={thumbUrl}
              alt={gallery.title}
              className="w-full h-full object-cover"
              loading="lazy"
              fallbackClassName="w-full h-full bg-vault-input"
            />
          ) : (
            <div
              className={`w-full h-full bg-gradient-to-b ${colors.bg} flex items-center justify-center`}
            >
              <span className={`text-sm font-semibold ${colors.text} opacity-70 text-center px-2`}>
                {gallery.category || t('library.categoryUncategorized')}
              </span>
            </div>
          )}

          {/* Source badge */}
          <div className="absolute bottom-1.5 left-1.5">
            <span
              className={`inline-block px-1.5 py-0.5 rounded border text-xs font-medium uppercase backdrop-blur-sm ${sourceStyle.className}`}
            >
              {sourceStyle.label}
            </span>
          </div>
        </div>

        {/* Info: one title line + one meta line, so the card height is a pure
            function of its width (estimateLibraryGridRowHeight reserves exactly this) */}
        <div className="flex flex-col gap-1 p-2">
          <h3
            className="text-vault-text text-sm font-medium truncate leading-5"
            title={title}
          >
            {title}
          </h3>

          <div className="flex items-center gap-1 h-4 text-xs leading-4">
            {rating > 0 && (
              <span
                className="shrink-0 text-yellow-400 tabular-nums"
                aria-label={t('common.ratingOf', { rating: String(rating) })}
              >
                ★{rating}
              </span>
            )}
            <span className="ml-auto min-w-0 truncate text-vault-text-muted">{gallery.pages}p</span>
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
