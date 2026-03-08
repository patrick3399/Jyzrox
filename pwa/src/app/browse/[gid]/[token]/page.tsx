'use client'

import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useEhGallery, useEhGalleryPreviews } from '@/hooks/useGalleries'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { RatingStars } from '@/components/RatingStars'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'

// Favorite category colors (from EhViewer)
const FAV_COLORS = ['#000', '#F44336', '#FF9800', '#FBC02D', '#4CAF50', '#8BC34A', '#03A9F4', '#3F51B5', '#9C27B0', '#E91E63']
const FAV_NAMES = ['Favorites 0', 'Favorites 1', 'Favorites 2', 'Favorites 3', 'Favorites 4', 'Favorites 5', 'Favorites 6', 'Favorites 7', 'Favorites 8', 'Favorites 9']

// ── Namespace colours (EhViewer style) ─────────────────────────────────

const NS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  female:    { bg: 'bg-pink-900/30',    text: 'text-pink-300',    border: 'border-pink-700' },
  male:      { bg: 'bg-blue-900/30',    text: 'text-blue-300',    border: 'border-blue-700' },
  artist:    { bg: 'bg-orange-900/30',   text: 'text-orange-300',  border: 'border-orange-700' },
  group:     { bg: 'bg-amber-900/30',    text: 'text-amber-300',   border: 'border-amber-700' },
  parody:    { bg: 'bg-green-900/30',    text: 'text-green-300',   border: 'border-green-700' },
  character: { bg: 'bg-purple-900/30',   text: 'text-purple-300',  border: 'border-purple-700' },
  language:  { bg: 'bg-cyan-900/30',     text: 'text-cyan-300',    border: 'border-cyan-700' },
  cosplayer: { bg: 'bg-rose-900/30',     text: 'text-rose-300',    border: 'border-rose-700' },
  mixed:     { bg: 'bg-teal-900/30',     text: 'text-teal-300',    border: 'border-teal-700' },
  other:     { bg: 'bg-gray-800',        text: 'text-gray-300',    border: 'border-gray-600' },
  reclass:   { bg: 'bg-red-900/30',      text: 'text-red-300',     border: 'border-red-700' },
}

function nsStyle(ns: string) {
  return NS_COLORS[ns] ?? NS_COLORS.other
}

// ── Category colours ───────────────────────────────────────────────────

const CATEGORY_COLOR: Record<string, string> = {
  doujinshi: '#F44336', manga: '#FF9800', artist_cg: '#FBC02D', game_cg: '#4CAF50',
  western: '#8BC34A', 'non-h': '#2196F3', image_set: '#3F51B5', cosplay: '#9C27B0',
  asian_porn: '#E91E63', misc: '#9E9E9E',
}

function getCatColor(cat: string) {
  return CATEGORY_COLOR[cat.toLowerCase().replace(/ /g, '_')] ?? '#607D8B'
}

function formatDate(unix: number) {
  return new Date(unix * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
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

  // Close fav picker on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (favRef.current && !favRef.current.contains(e.target as Node)) setShowFavPicker(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleAddFavorite = useCallback(async (favcat: number) => {
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
  }, [gallery])

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

  // Build first 6 preview thumbnails from previewData
  const previewThumbs = useMemo(() => {
    if (!previewData?.previews || !gallery) return []
    const count = Math.min(6, gallery.pages)
    const thumbs: { page: number; url: string; isSprite: boolean; offsetX?: number; width?: number; height?: number }[] = []
    for (let i = 1; i <= count; i++) {
      const raw = previewData.previews[String(i)]
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
  }, [previewData, gallery])

  const handleTagClick = useCallback((ns: string, name: string) => {
    const query = `${ns}:${name.replace(/ /g, '+')}`
    router.push(`/browse?q=${encodeURIComponent(query)}`)
  }, [router])

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

  const handleRead = useCallback((startPage = 1) => {
    router.push(`/browse/read/${gid}/${token}?page=${startPage}`)
  }, [router, gid, token])

  // ── Error / Loading ──

  if (galleryError) {
    return (
      <div className="min-h-screen bg-vault-bg text-vault-text flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 text-lg font-semibold">Failed to load gallery</p>
          <p className="text-sm text-vault-text-muted mt-1">{galleryError.message}</p>
          <button onClick={() => router.back()} className="mt-4 px-4 py-2 bg-vault-card rounded text-sm hover:bg-vault-card-hover">
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
    <div className="min-h-screen bg-vault-bg text-vault-text">
      <div className="max-w-5xl mx-auto px-4 py-5 space-y-6">

        {/* Back button */}
        <button
          onClick={() => router.back()}
          className="text-sm text-vault-text-muted hover:text-vault-text-secondary transition-colors"
        >
          {t('browse.backToBrowse')}
        </button>

        {/* ── Header section ── */}
        <div className="flex gap-5 flex-col sm:flex-row">
          {/* Cover */}
          <div className="flex-shrink-0 self-start">
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
                          className="w-3 h-3 rounded-full flex-shrink-0"
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
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">{t('common.tags')}</h2>
          <div className="space-y-2">
            {tagGroups.map(([ns, names]) => {
              const style = nsStyle(ns)
              return (
                <div key={ns} className="flex flex-wrap items-start gap-1.5">
                  {/* Namespace label */}
                  <span className={`text-[11px] font-bold px-2 py-1 rounded ${style.bg} ${style.text} ${style.border} border uppercase tracking-wide min-w-[70px] text-center flex-shrink-0`}>
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

        {/* ── Preview thumbnails (6 max) ── */}
        {previewThumbs.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">
              {t('browse.preview')} ({gallery.pages} pages)
            </h2>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {previewThumbs.map((thumb) => (
                <button
                  key={thumb.page}
                  onClick={() => handleRead(thumb.page)}
                  className="relative aspect-[3/4] bg-vault-bg rounded-lg overflow-hidden border border-vault-border
                             hover:border-blue-500 hover:brightness-110 transition-all cursor-pointer"
                >
                  {thumb.isSprite ? (
                    <div
                      className="w-full h-full"
                      style={{
                        backgroundImage: `url(${thumb.url})`,
                        backgroundPosition: `${thumb.offsetX}px 0`,
                        backgroundSize: 'auto 100%',
                        backgroundRepeat: 'no-repeat',
                      }}
                    />
                  ) : (
                    <img
                      src={thumb.url}
                      alt={`Page ${thumb.page}`}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                  )}
                  <span className="absolute bottom-0 left-0 right-0 bg-black/70 text-center text-[10px] text-white py-0.5">
                    {thumb.page}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
