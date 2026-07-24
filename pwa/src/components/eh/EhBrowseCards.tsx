'use client'

import { AppImage } from '@/components/AppImage'
import { RatingStars } from '@/components/RatingStars'
import { getEhGalleryLanguage } from '@/lib/ehGalleryLanguage'
import { t } from '@/lib/i18n'
import type { EhBrowseGalleryStatus, EhGallery } from '@/lib/types'

// ── IntersectionObserver-based lazy image ──────────────────────────────

// ── EhViewer category colour system (Material Design, from EhUtils.kt) ──

export const CATEGORY_META: Record<string, { color: string; label: string }> = {
  doujinshi: { color: '#F44336', label: 'browse.category.doujinshi' },
  manga: { color: '#FF9800', label: 'browse.category.manga' },
  artist_cg: { color: '#FBC02D', label: 'browse.category.artistCg' },
  game_cg: { color: '#4CAF50', label: 'browse.category.gameCg' },
  western: { color: '#8BC34A', label: 'browse.category.western' },
  'non-h': { color: '#2196F3', label: 'browse.category.nonH' },
  image_set: { color: '#3F51B5', label: 'browse.category.imageSet' },
  cosplay: { color: '#9C27B0', label: 'browse.category.cosplay' },
  asian_porn: { color: '#E91E63', label: 'browse.category.asianPorn' },
  misc: { color: '#9E9E9E', label: 'browse.category.misc' },
}
const UNKNOWN_COLOR = '#607D8B'

export function isLightColor(hex: string): boolean {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return (r * 299 + g * 587 + b * 114) / 1000 > 160
}

function getCategoryMeta(category: string) {
  const key = category.toLowerCase().replace(/ /g, '_')
  const meta = CATEGORY_META[key]
  return meta
    ? { color: meta.color, label: t(meta.label) }
    : { color: UNKNOWN_COLOR, label: category }
}

function formatDate(unix: number) {
  return new Date(unix * 1000).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

// ── List-mode card (EhViewer style) ────────────────────────────────────

export function ListCard({
  gallery,
  status,
  onClick,
  onUploaderClick,
}: {
  gallery: EhGallery
  status?: EhBrowseGalleryStatus
  onClick: () => void
  onUploaderClick: () => void
}) {
  const { color, label } = getCategoryMeta(gallery.category)
  const language = getEhGalleryLanguage(gallery)
  const thumbSrc = gallery.thumb
    ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}`
    : ''

  return (
    <article
      onClick={onClick}
      className="flex gap-3 p-3 bg-vault-card border border-vault-border rounded-lg cursor-pointer
                 hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors active:bg-vault-card-hover"
    >
      {/* Thumbnail */}
      <div className="shrink-0 w-[90px] h-[120px] bg-vault-input rounded overflow-hidden">
        {thumbSrc ? (
          <AppImage
            src={thumbSrc}
            alt={gallery.title}
            className="w-full h-full object-cover"
            fallbackClassName="w-full h-full bg-vault-input"
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center"
            style={{ background: color + '33' }}
          >
            <span className="text-xs font-bold" style={{ color }}>
              {label[0]}
            </span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex flex-col flex-1 min-w-0 gap-1.5">
        {/* Title */}
        <h3 className="text-sm font-medium text-vault-text line-clamp-2 leading-snug">
          {gallery.title || gallery.title_jpn}
        </h3>
        {gallery.title_jpn && gallery.title && (
          <p className="text-xs text-vault-text-muted line-clamp-1">{gallery.title_jpn}</p>
        )}

        {/* Uploader */}
        {gallery.uploader && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onUploaderClick()
            }}
            className="w-fit text-xs text-vault-text-muted hover:text-vault-accent transition-colors"
            title={t('browse.searchUploader', { uploader: gallery.uploader })}
          >
            {gallery.uploader}
          </button>
        )}

        {/* Bottom row */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-auto">
          {/* Category badge */}
          <span
            className="text-[11px] font-bold px-1.5 py-0.5 rounded text-white uppercase tracking-wide"
            style={{ backgroundColor: color }}
          >
            {label}
          </span>

          {language && (
            <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-cyan-900/80 text-cyan-100 border border-cyan-600/70">
              {language}
            </span>
          )}

          {/* Stars */}
          <RatingStars rating={gallery.rating} readonly />

          {/* Meta */}
          {status?.is_local_favorite && (
            <span className="text-xs text-pink-400" title={t('common.favorite')}>
              ♥
            </span>
          )}
          {status?.downloaded && (
            <span className="text-xs text-green-400" title={t('browse.download')}>
              ↓
            </span>
          )}
          <span className="text-xs text-vault-text-muted ml-auto">
            {status?.last_page ? `${status.last_page}/${gallery.pages}P` : `${gallery.pages}P`}
          </span>
          <span className="text-xs text-vault-text-muted">{formatDate(gallery.posted_at)}</span>
        </div>
      </div>
    </article>
  )
}

// ── Grid-mode card (EhViewer tile style) ────────────────────────────────

export function GridCard({
  gallery,
  status,
  onClick,
  onUploaderClick,
}: {
  gallery: EhGallery
  status?: EhBrowseGalleryStatus
  onClick: () => void
  onUploaderClick: () => void
}) {
  const { color, label } = getCategoryMeta(gallery.category)
  const language = getEhGalleryLanguage(gallery)
  const thumbSrc = gallery.thumb
    ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}`
    : ''

  return (
    <article
      onClick={onClick}
      className="relative aspect-[3/4] bg-vault-input rounded-lg overflow-hidden cursor-pointer
                 border border-vault-border hover:border-vault-border-hover transition-colors group"
    >
      {/* Thumbnail */}
      {thumbSrc ? (
        <AppImage
          src={thumbSrc}
          alt={gallery.title}
          className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
          fallbackClassName="w-full h-full bg-vault-input"
        />
      ) : (
        <div
          className="w-full h-full flex items-center justify-center"
          style={{ background: color + '33' }}
        >
          <span className="text-xl font-bold" style={{ color }}>
            {label[0]}
          </span>
        </div>
      )}

      {/* Gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />

      {/* Category badge (top-left) */}
      <span
        className="absolute top-1.5 left-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded text-white uppercase tracking-wide shadow-md"
        style={{ backgroundColor: color }}
      >
        {label}
      </span>

      {/* Pages (top-right) */}
      <span className="absolute top-1.5 right-1.5 text-[10px] text-white/80 bg-black/50 px-1 py-0.5 rounded">
        {status?.last_page ? `${status.last_page}/${gallery.pages}P` : `${gallery.pages}P`}
      </span>

      {language && (
        <span className="absolute top-8 right-1.5 text-[10px] font-bold text-cyan-100 bg-cyan-900/80 border border-cyan-500/70 px-1 py-0.5 rounded shadow-md">
          {language}
        </span>
      )}

      {/* Title overlay (bottom) */}
      <div className="absolute bottom-0 left-0 right-0 p-2">
        <p className="text-[11px] text-white font-medium line-clamp-2 leading-snug">
          {gallery.title || gallery.title_jpn}
        </p>
        {gallery.uploader && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onUploaderClick()
            }}
            className="block max-w-full truncate text-[10px] text-white/60 hover:text-vault-accent"
            title={t('browse.searchUploader', { uploader: gallery.uploader })}
          >
            {gallery.uploader}
          </button>
        )}
        <div className="flex items-center justify-between mt-1">
          <RatingStars rating={gallery.rating} readonly />
          <span className="flex items-center gap-1 text-[11px]">
            {status?.is_local_favorite && <span className="text-pink-400">♥</span>}
            {status?.downloaded && <span className="text-green-400">↓</span>}
          </span>
        </div>
      </div>
    </article>
  )
}
