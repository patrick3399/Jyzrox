'use client'

import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useEhGallery, useEhGalleryPreviews } from '@/hooks/useGalleries'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { RatingStars } from '@/components/RatingStars'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { BackButton } from '@/components/BackButton'
import type { EhComment } from '@/lib/types'

// ── Preview grid with scaled sprite offsets ─────────────────────────────

function PreviewGrid({
  thumbs,
  onRead,
}: {
  thumbs: {
    page: number
    url: string
    isSprite: boolean
    offsetX?: number
    width?: number
    height?: number
  }[]
  onRead: (page: number) => void
}) {
  const gridRef = useRef<HTMLDivElement>(null)
  const [cellW, setCellW] = useState(0)
  // Cache natural sprite dimensions per URL to compute pixel-perfect background-size.
  const [spriteNaturalSizes, setSpriteNaturalSizes] = useState<
    Record<string, { w: number; h: number }>
  >({})
  // Fixed cell height — tall enough for portrait; landscape gets letterboxed with object-contain logic.
  const CELL_H = 180

  useEffect(() => {
    const grid = gridRef.current
    if (!grid) return
    const measure = () => {
      const first = grid.firstElementChild as HTMLElement | null
      if (first) {
        // Use getBoundingClientRect for sub-pixel accuracy (offsetWidth rounds to integer).
        setCellW(first.getBoundingClientRect().width)
      }
    }
    measure()
    const obs = new ResizeObserver(measure)
    obs.observe(grid)
    return () => obs.disconnect()
  }, [thumbs.length])

  const spriteUrls = useMemo(
    () => [...new Set(thumbs.filter((t) => t.isSprite).map((t) => t.url))],
    [thumbs],
  )

  return (
    <>
      {/* Hidden imgs load the sprite's natural dimensions so we can set an exact
          background-size. Without this, `auto` relies on the browser's aspect-ratio
          calculation which may differ from the encoded cell dimensions by a pixel,
          causing cumulative offset errors that bleed adjacent cells into view. */}
      {spriteUrls.map((url) =>
        !spriteNaturalSizes[url] ? (
          <img
            key={url}
            src={url}
            style={{ display: 'none' }}
            alt=""
            onLoad={(e) => {
              const { naturalWidth: w, naturalHeight: h } = e.currentTarget
              setSpriteNaturalSizes((prev) => (prev[url] ? prev : { ...prev, [url]: { w, h } }))
            }}
          />
        ) : null,
      )}
      <div ref={gridRef} className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {thumbs.map((thumb) => {
          // object-contain scale: fit entire cell within container, no cropping.
          // This handles both portrait and landscape images correctly.
          const tw = thumb.width ?? 200
          const th = thumb.height ?? 300
          const scaleX = cellW ? cellW / tw : 1
          // Use fixed CELL_H for consistent grid rows regardless of image orientation.
          const scaleY = CELL_H / th
          // Use Math.max (cover) so images fill the cell on both axes;
          // overflow is clipped by the container's overflow-hidden.
          const scale = Math.max(scaleX, scaleY)
          const naturalSize = spriteNaturalSizes[thumb.url]
          // Use exact pixel dimensions once the sprite is loaded; fall back to auto
          // until then. This prevents sub-pixel rounding from bleeding adjacent cells.
          const bgSize = naturalSize
            ? `${naturalSize.w * scale}px ${naturalSize.h * scale}px`
            : `${tw * scale}px ${th * scale}px`
          // Background-position: shift the sprite left so that the desired cell
          // starts at the container's origin, then add centering offset so the
          // (smaller) cell is centered horizontally within the container.
          const scaledCellW = tw * scale
          const bgPosX = (thumb.offsetX ?? 0) * scale + (cellW - scaledCellW) / 2
          return (
            <button
              key={thumb.page}
              onClick={() => onRead(thumb.page)}
              className="relative bg-vault-bg rounded-lg overflow-hidden border border-vault-border
                         hover:border-blue-500 hover:brightness-110 transition-all cursor-pointer flex items-center justify-center"
              style={{ height: CELL_H }}
            >
              {thumb.isSprite ? (
                <div
                  className="w-full h-full"
                  style={{
                    backgroundImage: `url(${thumb.url})`,
                    backgroundPosition: `${bgPosX}px top`,
                    backgroundSize: bgSize,
                    backgroundRepeat: 'no-repeat',
                  }}
                />
              ) : (
                <img
                  src={thumb.url}
                  alt={`Page ${thumb.page}`}
                  className="w-full h-full object-cover"
                />
              )}
              <span className="absolute bottom-0 left-0 right-0 bg-black/70 text-center text-[10px] text-white py-0.5">
                {thumb.page}
              </span>
            </button>
          )
        })}
      </div>
    </>
  )
}

// Favorite category colors (from EhViewer)
const FAV_COLORS = [
  '#000',
  '#F44336',
  '#FF9800',
  '#FBC02D',
  '#4CAF50',
  '#8BC34A',
  '#03A9F4',
  '#3F51B5',
  '#9C27B0',
  '#E91E63',
]
const FAV_NAMES = [
  'Favorites 0',
  'Favorites 1',
  'Favorites 2',
  'Favorites 3',
  'Favorites 4',
  'Favorites 5',
  'Favorites 6',
  'Favorites 7',
  'Favorites 8',
  'Favorites 9',
]

// ── Namespace colours (EhViewer style) ─────────────────────────────────

const NS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  female: { bg: 'bg-pink-900/30', text: 'text-pink-300', border: 'border-pink-700' },
  male: { bg: 'bg-blue-900/30', text: 'text-blue-300', border: 'border-blue-700' },
  artist: { bg: 'bg-orange-900/30', text: 'text-orange-300', border: 'border-orange-700' },
  group: { bg: 'bg-amber-900/30', text: 'text-amber-300', border: 'border-amber-700' },
  parody: { bg: 'bg-green-900/30', text: 'text-green-300', border: 'border-green-700' },
  character: { bg: 'bg-purple-900/30', text: 'text-purple-300', border: 'border-purple-700' },
  language: { bg: 'bg-cyan-900/30', text: 'text-cyan-300', border: 'border-cyan-700' },
  cosplayer: { bg: 'bg-rose-900/30', text: 'text-rose-300', border: 'border-rose-700' },
  mixed: { bg: 'bg-teal-900/30', text: 'text-teal-300', border: 'border-teal-700' },
  other: { bg: 'bg-gray-800', text: 'text-gray-300', border: 'border-gray-600' },
  reclass: { bg: 'bg-red-900/30', text: 'text-red-300', border: 'border-red-700' },
}

function nsStyle(ns: string) {
  return NS_COLORS[ns] ?? NS_COLORS.other
}

// ── Category colours ───────────────────────────────────────────────────

const CATEGORY_COLOR: Record<string, string> = {
  doujinshi: '#F44336',
  manga: '#FF9800',
  artist_cg: '#FBC02D',
  game_cg: '#4CAF50',
  western: '#8BC34A',
  'non-h': '#2196F3',
  image_set: '#3F51B5',
  cosplay: '#9C27B0',
  asian_porn: '#E91E63',
  misc: '#9E9E9E',
}

function getCatColor(cat: string) {
  return CATEGORY_COLOR[cat.toLowerCase().replace(/ /g, '_')] ?? '#607D8B'
}

function formatDate(unix: number) {
  return new Date(unix * 1000).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ── Main page ──────────────────────────────────────────────────────────

export default function EhGalleryDetailPage() {
  const { gid: gidStr, token } = useParams<{ gid: string; token: string }>()
  const gid = Number(gidStr)
  const router = useRouter()

  const { data: gallery, error: galleryError } = useEhGallery(gid, token)
  const { data: previewData } = useEhGalleryPreviews(gid, token)

  // Favorite state
  const [showFavPicker, setShowFavPicker] = useState(false)
  const [favSaving, setFavSaving] = useState(false)
  const [isFavorited, setIsFavorited] = useState(false)
  const favRef = useRef<HTMLDivElement>(null)

  // Load More previews state
  const [extraPreviews, setExtraPreviews] = useState<Record<string, string>>({})
  const [hasMore, setHasMore] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [infiniteScroll, setInfiniteScroll] = useState(false) // enabled after first Load More
  const sentinelRef = useRef<HTMLDivElement>(null)

  // Close fav picker on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (favRef.current && !favRef.current.contains(e.target as Node)) setShowFavPicker(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Record browse history once when gallery data is loaded
  const historyRecordedRef = useRef(false)
  useEffect(() => {
    if (!gallery || historyRecordedRef.current) return
    try {
      if (localStorage.getItem('history_enabled') !== 'false') {
        historyRecordedRef.current = true
        api.history
          .record({
            source: 'ehentai',
            source_id: String(gid),
            title: gallery.title_jpn || gallery.title,
            thumb: gallery.thumb,
            gid: Number(gid),
            token,
          })
          .catch(() => {})
      }
    } catch {
      // localStorage may be unavailable in some contexts
    }
  }, [gallery, gid, token])

  const handleAddFavorite = useCallback(
    async (favcat: number) => {
      if (!gallery) return
      setFavSaving(true)
      try {
        await api.eh.addFavorite(gallery.gid, gallery.token, favcat)
        toast.success(`Added to Favorites ${favcat}`)
        setIsFavorited(true)
        setShowFavPicker(false)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to add favorite')
      } finally {
        setFavSaving(false)
      }
    },
    [gallery],
  )

  const handleRemoveFavorite = useCallback(async () => {
    if (!gallery) return
    setFavSaving(true)
    try {
      await api.eh.removeFavorite(gallery.gid, gallery.token)
      toast.success('Removed from favorites')
      setIsFavorited(false)
      setShowFavPicker(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove favorite')
    } finally {
      setFavSaving(false)
    }
  }, [gallery])

  // Group tags by namespace
  const tagGroups = useMemo(() => {
    if (!gallery) return []
    const groups: Record<string, string[]> = {}
    for (const tag of gallery.tags) {
      const colonIdx = tag.indexOf(':')
      const ns = colonIdx !== -1 ? tag.slice(0, colonIdx) : 'misc'
      const name = colonIdx !== -1 ? tag.slice(colonIdx + 1) : tag
      if (!groups[ns]) groups[ns] = []
      groups[ns].push(name)
    }
    // Sort: female/male first, then alphabetical
    const priority = ['female', 'male', 'artist', 'group', 'parody', 'character', 'language']
    return Object.entries(groups).sort(([a], [b]) => {
      const ai = priority.indexOf(a)
      const bi = priority.indexOf(b)
      if (ai !== -1 && bi !== -1) return ai - bi
      if (ai !== -1) return -1
      if (bi !== -1) return 1
      return a.localeCompare(b)
    })
  }, [gallery])

  // Build preview thumbnails from all available preview data
  const previewThumbs = useMemo(() => {
    if (!previewData?.previews || !gallery) return []
    const allPreviews = { ...previewData.previews, ...extraPreviews }
    const maxPage = Math.max(0, ...Object.keys(allPreviews).map(Number))
    const thumbs: {
      page: number
      url: string
      isSprite: boolean
      offsetX?: number
      width?: number
      height?: number
    }[] = []
    for (let i = 1; i <= maxPage; i++) {
      const raw = allPreviews[String(i)]
      if (!raw) continue
      if (raw.includes('|')) {
        const [spriteUrl, ox, w, h] = raw.split('|')
        thumbs.push({
          page: i,
          url: api.eh.thumbProxyUrl(spriteUrl),
          isSprite: true,
          offsetX: parseInt(ox),
          width: parseInt(w),
          height: parseInt(h),
        })
      } else {
        thumbs.push({ page: i, url: api.eh.thumbProxyUrl(raw), isSprite: false })
      }
    }
    return thumbs
  }, [previewData, extraPreviews, gallery])

  const handleTagClick = useCallback(
    (ns: string, name: string) => {
      const query = name.includes(' ') ? `${ns}:"${name}"` : `${ns}:${name}`
      router.push(`/e-hentai?q=${encodeURIComponent(query)}`)
    },
    [router],
  )

  const handleDownload = useCallback(async () => {
    if (!gallery) return
    try {
      const url = `https://e-hentai.org/g/${gallery.gid}/${gallery.token}/`
      const res = await api.download.enqueue(url, 'ehentai')
      toast.success(`Added to queue (job: ${res.job_id})`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }, [gallery])

  const handleRead = useCallback(
    (startPage = 1) => {
      router.push(`/e-hentai/read/${gid}/${token}?page=${startPage}`)
    },
    [router, gid, token],
  )

  const loadMorePreviews = useCallback(async () => {
    if (!gallery || loadingMore || !hasMore) return

    setLoadingMore(true)
    try {
      // Start from the highest page we already have
      const allKeys = [
        ...Object.keys(previewData?.previews || {}),
        ...Object.keys(extraPreviews),
      ].map(Number)
      const startPage = allKeys.length > 0 ? Math.max(...allKeys) : 0
      const result = await api.eh.getImagesPaginated(gallery.gid, gallery.token, startPage, 30)
      setExtraPreviews((prev) => ({ ...prev, ...result.previews }))
      setHasMore(result.has_more)
      setInfiniteScroll(true)
    } catch {
      toast.error(t('common.loadFailed'))
    } finally {
      setLoadingMore(false)
    }
  }, [gallery, previewData, extraPreviews, loadingMore, hasMore])

  // Infinite scroll: auto-load when sentinel enters viewport
  useEffect(() => {
    if (!infiniteScroll || !hasMore || !sentinelRef.current) return
    const sentinel = sentinelRef.current
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMorePreviews()
        }
      },
      { rootMargin: '200px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [infiniteScroll, hasMore, loadMorePreviews])

  // ── Keyboard navigation ──

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        router.push(`/e-hentai/read/${gid}/${token}?page=1`)
      }
      if (e.key === 'ArrowUp' || e.key === 'Escape') {
        e.preventDefault()
        history.length > 1 ? router.back() : router.push('/e-hentai')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [router, gid, token])

  // ── Error / Loading ──

  if (galleryError) {
    return (
      <div className="min-h-screen bg-vault-bg text-vault-text flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 text-lg font-semibold">Failed to load gallery</p>
          <p className="text-sm text-vault-text-muted mt-1">{galleryError.message}</p>
          <button
            onClick={() => router.back()}
            className="mt-4 px-4 py-2 bg-vault-card rounded text-sm hover:bg-vault-card-hover"
          >
            Go back
          </button>
        </div>
      </div>
    )
  }

  if (!gallery) {
    return (
      <div className="min-h-screen bg-vault-bg text-vault-text flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  const catColor = getCatColor(gallery.category)
  const thumbSrc = gallery.thumb
    ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}`
    : ''

  return (
    <>
      <div className="space-y-6">
        {/* ── Header section ── */}
        <div className="flex gap-5 flex-col sm:flex-row">
          {/* Cover */}
          <div className="shrink-0 self-start">
            {thumbSrc ? (
              <img
                src={thumbSrc}
                alt={gallery.title}
                className="w-48 h-64 object-cover rounded-lg shadow-lg cursor-pointer hover:opacity-90 transition-opacity"
                onClick={() => handleRead(1)}
              />
            ) : (
              <div className="w-48 h-64 rounded-lg bg-vault-card flex items-center justify-center">
                <span className="text-4xl font-bold" style={{ color: catColor }}>
                  {gallery.category[0]}
                </span>
              </div>
            )}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0 space-y-3">
            <h1 className="text-xl font-bold leading-snug">{gallery.title}</h1>
            {gallery.title_jpn && (
              <p className="text-sm text-vault-text-secondary">{gallery.title_jpn}</p>
            )}

            {/* Meta row */}
            <div className="flex flex-wrap gap-2 text-xs">
              <span
                className="px-2 py-1 rounded font-bold text-white uppercase tracking-wide"
                style={{ backgroundColor: catColor }}
              >
                {gallery.category}
              </span>
              <span className="px-2 py-1 rounded bg-vault-card border border-vault-border text-vault-text-secondary">
                {gallery.pages} pages
              </span>
              {gallery.uploader && (
                <span className="px-2 py-1 rounded bg-vault-card border border-vault-border text-vault-text-secondary">
                  {gallery.uploader}
                </span>
              )}
              <span className="px-2 py-1 rounded bg-vault-card border border-vault-border text-vault-text-secondary">
                {formatDate(gallery.posted_at)}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <RatingStars rating={gallery.rating} readonly />
              <span className="text-sm text-vault-text-muted">{gallery.rating.toFixed(2)}</span>
            </div>

            {/* Action buttons */}
            <div className="flex gap-3 pt-1">
              <button
                onClick={() => handleRead(1)}
                className="px-6 py-2.5 bg-vault-accent hover:bg-vault-accent/90 rounded-lg text-white text-sm font-medium transition-colors"
              >
                {t('browse.read')}
              </button>
              <button
                onClick={handleDownload}
                className="px-6 py-2.5 bg-green-700 hover:bg-green-600 rounded-lg text-white text-sm font-medium transition-colors"
              >
                {t('browse.download')}
              </button>
              {/* Favorite button with picker */}
              <div className="relative" ref={favRef}>
                <button
                  onClick={() => setShowFavPicker((v) => !v)}
                  disabled={favSaving}
                  className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    isFavorited
                      ? 'bg-pink-700 hover:bg-pink-600 text-white'
                      : 'bg-vault-card border border-vault-border hover:border-vault-border-hover text-vault-text-secondary'
                  }`}
                  title="Favorite"
                >
                  {isFavorited ? '♥' : '♡'}
                </button>
                {showFavPicker && (
                  <div className="absolute top-full left-0 mt-1 z-50 bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden min-w-[180px]">
                    {FAV_NAMES.map((name, i) => (
                      <button
                        key={i}
                        onClick={() => handleAddFavorite(i)}
                        disabled={favSaving}
                        className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-vault-text hover:bg-vault-card-hover transition-colors"
                      >
                        <span
                          className="w-3 h-3 rounded-full shrink-0"
                          style={{ backgroundColor: FAV_COLORS[i] }}
                        />
                        {name}
                      </button>
                    ))}
                    {isFavorited && (
                      <>
                        <div className="border-t border-vault-border" />
                        <button
                          onClick={handleRemoveFavorite}
                          disabled={favSaving}
                          className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-vault-card-hover transition-colors"
                        >
                          Remove from favorites
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── Tags section (grouped by namespace) ── */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">
            {t('common.tags')}
          </h2>
          <div className="space-y-2">
            {tagGroups.map(([ns, names]) => {
              const style = nsStyle(ns)
              return (
                <div key={ns} className="flex flex-wrap items-start gap-1.5">
                  {/* Namespace label */}
                  <span
                    className={`text-[11px] font-bold px-2 py-1 rounded ${style.bg} ${style.text} ${style.border} border uppercase tracking-wide min-w-[70px] text-center shrink-0`}
                  >
                    {ns}
                  </span>
                  {/* Tag buttons */}
                  {names.map((name) => (
                    <button
                      key={`${ns}:${name}`}
                      onClick={() => handleTagClick(ns, name)}
                      className={`text-xs px-2 py-1 rounded border transition-all cursor-pointer
                                  ${style.bg} ${style.border} ${style.text}
                                  hover:brightness-125 hover:scale-[1.02] active:scale-[0.98]`}
                      title={`Search for ${ns}:${name}`}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Preview thumbnails ── */}
        {previewThumbs.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">
              {t('browse.preview')} ({gallery.pages} {t('browse.pages')})
            </h2>
            <PreviewGrid thumbs={previewThumbs} onRead={handleRead} />
            {gallery.pages > previewThumbs.length && hasMore && !infiniteScroll && (
              <button
                onClick={loadMorePreviews}
                disabled={loadingMore}
                className="w-full py-2.5 rounded-lg border border-vault-border text-vault-text-secondary text-sm
                           hover:bg-vault-hover hover:text-vault-text transition-colors disabled:opacity-50"
              >
                {loadingMore ? t('common.loading') : t('browse.loadMorePreviews')}
              </button>
            )}
            {infiniteScroll && hasMore && (
              <div ref={sentinelRef} className="flex justify-center py-4">
                {loadingMore && <LoadingSpinner />}
              </div>
            )}
          </div>
        )}
      </div>

      <BackButton fallback="/e-hentai" />
    </>
  )
}
