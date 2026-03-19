'use client'
import { useState, useCallback } from 'react'
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
import type { Gallery, EhGallery } from '@/lib/types'
import { RatingStars } from './RatingStars'
import { ContextMenu } from './ContextMenu'
import { useLongPress } from '@/hooks/useLongPress'
import { getSourceStyle, getEventPosition } from '@/lib/galleryUtils'
import { t } from '@/lib/i18n'

// ── Category colours ──────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, { bg: string; text: string; badge: string }> = {
  Doujinshi: { bg: 'from-pink-950 to-pink-900', text: 'text-pink-300', badge: 'bg-pink-700' },
  Manga: { bg: 'from-orange-950 to-orange-900', text: 'text-orange-300', badge: 'bg-orange-700' },
  'Artist CG': {
    bg: 'from-yellow-950 to-yellow-900',
    text: 'text-yellow-300',
    badge: 'bg-yellow-700',
  },
  'Game CG': { bg: 'from-green-950 to-green-900', text: 'text-green-300', badge: 'bg-green-700' },
  Western: { bg: 'from-sky-950 to-sky-900', text: 'text-sky-300', badge: 'bg-sky-700' },
  'Non-H': { bg: 'from-blue-950 to-blue-900', text: 'text-blue-300', badge: 'bg-blue-700' },
  'Image Set': {
    bg: 'from-purple-950 to-purple-900',
    text: 'text-purple-300',
    badge: 'bg-purple-700',
  },
  Cosplay: { bg: 'from-red-950 to-red-900', text: 'text-red-300', badge: 'bg-red-700' },
  'Asian Porn': { bg: 'from-rose-950 to-rose-900', text: 'text-rose-300', badge: 'bg-rose-700' },
  Misc: { bg: 'from-gray-900 to-gray-800', text: 'text-gray-300', badge: 'bg-gray-600' },
}

function getCategoryColors(category: string) {
  return CATEGORY_COLORS[category] || CATEGORY_COLORS['Misc']
}

// ── EhGalleryCard ─────────────────────────────────────────────────────

interface EhCardProps {
  gallery: EhGallery
  onClick?: () => void
}

export function EhGalleryCard({ gallery, onClick }: EhCardProps) {
  const colors = getCategoryColors(gallery.category)
  const router = useRouter()

  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPos, setMenuPos] = useState({ x: 0, y: 0 })

  const handleLongPress = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    e.preventDefault()
    setMenuPos(getEventPosition(e))
    setMenuOpen(true)
  }, [])

  const longPressHandlers = useLongPress({ onLongPress: handleLongPress })

  // Detail URL: E-Hentai galleries use the gallery_id / gallery_token fields.
  // Navigate to the detail page if the gallery object carries those fields;
  // otherwise fall back to the source URL stored in `thumb`.
  const handleOpenDetail = useCallback(() => {
    const g = gallery as EhGallery & { gallery_id?: number; gallery_token?: string; url?: string }
    if (g.gallery_id && g.gallery_token) {
      router.push(`/eh/${g.gallery_id}/${g.gallery_token}`)
    } else if (g.url) {
      window.open(g.url, '_blank', 'noopener,noreferrer')
    }
  }, [gallery, router])

  const contextItems = [
    {
      label: t('contextMenu.read'),
      icon: BookOpen,
      onClick: () => onClick?.(),
    },
    {
      label: t('contextMenu.openDetail'),
      icon: ExternalLink,
      onClick: handleOpenDetail,
    },
  ]

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
          bg-vault-card border border-vault-border rounded-lg overflow-hidden
          transition-all duration-200 cursor-pointer
          hover:scale-[1.02] hover:border-vault-accent hover:shadow-lg hover:shadow-vault-accent/20 hover:brightness-105
          focus:outline-none focus:ring-2 focus:ring-vault-accent
        `}
      >
        {/* Thumbnail */}
        <div className="relative aspect-[3/4] bg-vault-bg overflow-hidden">
          <img
            src={
              gallery.thumb ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}` : ''
            }
            alt={gallery.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
          {/* Category badge */}
          <span
            className={`
              absolute top-1.5 left-1.5
              px-1.5 py-0.5 rounded text-xs font-semibold
              ${colors.badge} text-white
              shadow
            `}
          >
            {gallery.category || t('library.categoryUncategorized')}
          </span>
        </div>

        {/* Info */}
        <div className="flex flex-col gap-1.5 p-2.5 flex-1">
          <h3 className="text-vault-text text-sm font-medium line-clamp-2 leading-snug">
            {gallery.title || gallery.title_jpn}
          </h3>

          <div className="flex items-center justify-between mt-auto pt-1">
            <RatingStars rating={gallery.rating} readonly />
            <span className="text-xs text-vault-text-muted">{gallery.pages}p</span>
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

// ── LibraryGalleryCard ────────────────────────────────────────────────

interface LibraryCardProps {
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

export function LibraryGalleryCard({
  gallery,
  thumbUrl,
  onClick,
  selected,
  selectMode,
  onFavoriteToggle,
  onReadingListToggle,
  onDelete,
  onDownload,
}: LibraryCardProps) {
  const colors = getCategoryColors(gallery.category)
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
            <img
              src={thumbUrl}
              alt={gallery.title}
              className="w-full h-full object-cover"
              loading="lazy"
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

        {/* Info */}
        <div className="flex flex-col gap-1.5 p-2.5 flex-1">
          <h3 className="text-vault-text text-sm font-medium line-clamp-2 leading-snug">
            {gallery.title || gallery.title_jpn}
          </h3>

          <div className="flex items-center justify-between mt-auto pt-1">
            <RatingStars rating={gallery.my_rating ?? gallery.rating} readonly />
            <span className="text-xs text-vault-text-muted">{gallery.pages}p</span>
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
