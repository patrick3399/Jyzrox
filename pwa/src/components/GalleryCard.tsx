import type { Gallery, EhGallery } from '@/lib/types'
import { RatingStars } from './RatingStars'
import { DownloadStatusBadge } from './DownloadStatusBadge'

// ── Category colours ──────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, { bg: string; text: string; badge: string }> = {
  Doujinshi:    { bg: 'from-pink-950 to-pink-900',    text: 'text-pink-300',    badge: 'bg-pink-700' },
  Manga:        { bg: 'from-orange-950 to-orange-900', text: 'text-orange-300',  badge: 'bg-orange-700' },
  'Artist CG':  { bg: 'from-yellow-950 to-yellow-900', text: 'text-yellow-300',  badge: 'bg-yellow-700' },
  'Game CG':    { bg: 'from-green-950 to-green-900',   text: 'text-green-300',   badge: 'bg-green-700' },
  Western:      { bg: 'from-sky-950 to-sky-900',       text: 'text-sky-300',     badge: 'bg-sky-700' },
  'Non-H':      { bg: 'from-blue-950 to-blue-900',     text: 'text-blue-300',    badge: 'bg-blue-700' },
  'Image Set':  { bg: 'from-purple-950 to-purple-900', text: 'text-purple-300',  badge: 'bg-purple-700' },
  Cosplay:      { bg: 'from-red-950 to-red-900',       text: 'text-red-300',     badge: 'bg-red-700' },
  'Asian Porn': { bg: 'from-rose-950 to-rose-900',     text: 'text-rose-300',    badge: 'bg-rose-700' },
  Misc:         { bg: 'from-gray-900 to-gray-800',     text: 'text-gray-300',    badge: 'bg-gray-600' },
}

function getCategoryColors(category: string) {
  return CATEGORY_COLORS[category] ?? CATEGORY_COLORS['Misc']
}

// ── EhGalleryCard ─────────────────────────────────────────────────────

interface EhCardProps {
  gallery: EhGallery
  onClick?: () => void
}

export function EhGalleryCard({ gallery, onClick }: EhCardProps) {
  const colors = getCategoryColors(gallery.category)

  return (
    <article
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
      className={`
        relative flex flex-col
        bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg overflow-hidden
        transition-all duration-200 cursor-pointer
        hover:scale-[1.02] hover:border-purple-500 hover:shadow-lg hover:shadow-purple-900/30
        focus:outline-none focus:ring-2 focus:ring-purple-500
      `}
    >
      {/* Thumbnail */}
      <div className="relative aspect-[3/4] bg-gray-900 overflow-hidden">
        <img
          src={gallery.thumb}
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
          {gallery.category}
        </span>
      </div>

      {/* Info */}
      <div className="flex flex-col gap-1.5 p-2.5 flex-1">
        <h3 className="text-gray-200 text-sm font-medium line-clamp-2 leading-snug">
          {gallery.title || gallery.title_jpn}
        </h3>

        <div className="flex items-center justify-between mt-auto pt-1">
          <RatingStars rating={gallery.rating} readonly />
          <span className="text-xs text-gray-500">{gallery.pages}p</span>
        </div>
      </div>
    </article>
  )
}

// ── LibraryGalleryCard ────────────────────────────────────────────────

interface LibraryCardProps {
  gallery: Gallery
  thumbUrl?: string
  onClick?: () => void
}

export function LibraryGalleryCard({ gallery, thumbUrl, onClick }: LibraryCardProps) {
  const colors = getCategoryColors(gallery.category)

  return (
    <article
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
      className={`
        relative flex flex-col
        bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg overflow-hidden
        transition-all duration-200 cursor-pointer
        hover:scale-[1.02] hover:border-purple-500 hover:shadow-lg hover:shadow-purple-900/30
        focus:outline-none focus:ring-2 focus:ring-purple-500
      `}
    >
      {/* Favourite indicator */}
      {gallery.favorited && (
        <span
          className="absolute top-1.5 right-1.5 z-10 text-red-400 text-base leading-none drop-shadow"
          aria-label="Favourited"
        >
          ♥
        </span>
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
              {gallery.category}
            </span>
          </div>
        )}

        {/* Download status badge */}
        <div className="absolute bottom-1.5 left-1.5">
          <DownloadStatusBadge status={gallery.download_status} />
        </div>
      </div>

      {/* Info */}
      <div className="flex flex-col gap-1.5 p-2.5 flex-1">
        <h3 className="text-gray-200 text-sm font-medium line-clamp-2 leading-snug">
          {gallery.title || gallery.title_jpn}
        </h3>

        <div className="flex items-center justify-between mt-auto pt-1">
          <RatingStars rating={gallery.rating} readonly />
          <span className="text-xs text-gray-500">{gallery.pages}p</span>
        </div>
      </div>
    </article>
  )
}
