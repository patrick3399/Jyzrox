'use client'

import { useState, useRef, useCallback } from 'react'
import { useEhSearch } from '@/hooks/useGalleries'
import { api } from '@/lib/api'
import { Pagination } from '@/components/Pagination'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AlertBanner } from '@/components/AlertBanner'
import { RatingStars } from '@/components/RatingStars'
import type { EhGallery } from '@/lib/types'

// ── EhViewer category colour system (Material Design, from EhUtils.kt) ──

const CATEGORY_META: Record<string, { color: string; label: string }> = {
  doujinshi:  { color: '#F44336', label: 'Doujinshi' },
  manga:      { color: '#FF9800', label: 'Manga' },
  artist_cg:  { color: '#FBC02D', label: 'Artist CG' },
  game_cg:    { color: '#4CAF50', label: 'Game CG' },
  western:    { color: '#8BC34A', label: 'Western' },
  'non-h':    { color: '#2196F3', label: 'Non-H' },
  image_set:  { color: '#3F51B5', label: 'Image Set' },
  cosplay:    { color: '#9C27B0', label: 'Cosplay' },
  asian_porn: { color: '#E91E63', label: 'Asian Porn' },
  misc:       { color: '#9E9E9E', label: 'Misc' },
}
const UNKNOWN_COLOR = '#607D8B'

function isLightColor(hex: string): boolean {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return (r * 299 + g * 587 + b * 114) / 1000 > 160
}

function getCategoryMeta(category: string) {
  const key = category.toLowerCase().replace(/ /g, '_')
  return CATEGORY_META[key] ?? { color: UNKNOWN_COLOR, label: category }
}

function formatDate(unix: number) {
  return new Date(unix * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

// ── List-mode card (EhViewer style) ────────────────────────────────────

function ListCard({ gallery, onClick }: { gallery: EhGallery; onClick: () => void }) {
  const { color, label } = getCategoryMeta(gallery.category)
  const thumbSrc = gallery.thumb
    ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}`
    : ''

  return (
    <article
      onClick={onClick}
      className="flex gap-3 p-3 bg-[#111111] border border-[#252525] rounded-lg cursor-pointer
                 hover:border-[#3a3a3a] hover:bg-[#161616] transition-colors active:bg-[#1e1e1e]"
    >
      {/* Thumbnail */}
      <div className="flex-shrink-0 w-[90px] h-[120px] bg-[#1a1a1a] rounded overflow-hidden">
        {thumbSrc ? (
          <img
            src={thumbSrc}
            alt={gallery.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center" style={{ background: color + '33' }}>
            <span className="text-xs font-bold" style={{ color }}>{label[0]}</span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex flex-col flex-1 min-w-0 gap-1.5">
        {/* Title */}
        <h3 className="text-sm font-medium text-gray-100 line-clamp-2 leading-snug">
          {gallery.title || gallery.title_jpn}
        </h3>
        {gallery.title_jpn && gallery.title && (
          <p className="text-xs text-gray-500 line-clamp-1">{gallery.title_jpn}</p>
        )}

        {/* Uploader */}
        <p className="text-xs text-gray-500">{gallery.uploader}</p>

        {/* Bottom row */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-auto">
          {/* Category badge */}
          <span
            className="text-[11px] font-bold px-1.5 py-0.5 rounded text-white uppercase tracking-wide"
            style={{ backgroundColor: color }}
          >
            {label}
          </span>

          {/* Stars */}
          <RatingStars rating={gallery.rating} readonly />

          {/* Meta */}
          <span className="text-xs text-gray-600 ml-auto">{gallery.pages}P</span>
          <span className="text-xs text-gray-600">{formatDate(gallery.posted_at)}</span>
        </div>
      </div>
    </article>
  )
}

// ── Grid-mode card (EhViewer tile style) ────────────────────────────────

function GridCard({ gallery, onClick }: { gallery: EhGallery; onClick: () => void }) {
  const { color, label } = getCategoryMeta(gallery.category)
  const thumbSrc = gallery.thumb
    ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}`
    : ''

  return (
    <article
      onClick={onClick}
      className="relative aspect-[3/4] bg-[#1a1a1a] rounded-lg overflow-hidden cursor-pointer
                 border border-[#252525] hover:border-[#444] transition-colors group"
    >
      {/* Thumbnail */}
      {thumbSrc ? (
        <img
          src={thumbSrc}
          alt={gallery.title}
          className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
          loading="lazy"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center" style={{ background: color + '33' }}>
          <span className="text-xl font-bold" style={{ color }}>{label[0]}</span>
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
        {gallery.pages}P
      </span>

      {/* Title overlay (bottom) */}
      <div className="absolute bottom-0 left-0 right-0 p-2">
        <p className="text-[11px] text-white font-medium line-clamp-2 leading-snug">
          {gallery.title || gallery.title_jpn}
        </p>
        <div className="flex items-center justify-between mt-1">
          <RatingStars rating={gallery.rating} readonly />
        </div>
      </div>
    </article>
  )
}

// ── Gallery detail modal ────────────────────────────────────────────────

function GalleryModal({
  gallery,
  onClose,
  onDownload,
}: {
  gallery: EhGallery
  onClose: () => void
  onDownload: (g: EhGallery) => void
}) {
  const { color, label } = getCategoryMeta(gallery.category)
  const thumbSrc = gallery.thumb
    ? `/api/eh/thumb-proxy?url=${encodeURIComponent(gallery.thumb)}`
    : ''

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[#111111] border border-[#2a2a2a] rounded-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex gap-4 p-5">
          {/* Thumbnail */}
          <div className="flex-shrink-0">
            {thumbSrc ? (
              <img
                src={thumbSrc}
                alt={gallery.title}
                className="w-36 h-48 object-cover rounded-lg shadow-md"
              />
            ) : (
              <div
                className="w-36 h-48 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: color + '33' }}
              >
                <span className="text-3xl font-bold" style={{ color }}>{label[0]}</span>
              </div>
            )}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0 flex flex-col gap-2">
            <h2 className="text-base font-semibold text-white leading-snug">{gallery.title}</h2>
            {gallery.title_jpn && (
              <p className="text-sm text-gray-400 -mt-1">{gallery.title_jpn}</p>
            )}

            {/* Meta chips */}
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span
                className="px-2 py-0.5 rounded font-bold text-white uppercase tracking-wide"
                style={{ backgroundColor: color }}
              >
                {label}
              </span>
              <span className="px-2 py-0.5 rounded bg-[#1a1a1a] border border-[#333] text-gray-400">
                {gallery.pages} pages
              </span>
              <span className="px-2 py-0.5 rounded bg-[#1a1a1a] border border-[#333] text-gray-400">
                {formatDate(gallery.posted_at)}
              </span>
              {gallery.uploader && (
                <span className="px-2 py-0.5 rounded bg-[#1a1a1a] border border-[#333] text-gray-400">
                  {gallery.uploader}
                </span>
              )}
            </div>

            {/* Rating */}
            <div className="flex items-center gap-2">
              <RatingStars rating={gallery.rating} readonly />
              <span className="text-xs text-gray-500">{gallery.rating.toFixed(1)}</span>
            </div>

            {/* Tags */}
            <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto pr-1">
              {gallery.tags.map((tag) => {
                const [ns, ...rest] = tag.split(':')
                const isNs = rest.length > 0
                return (
                  <span
                    key={tag}
                    className="text-[11px] px-1.5 py-0.5 rounded border font-mono
                               bg-[#1a1a1a] border-[#333] text-gray-400"
                  >
                    {isNs && <span className="text-gray-600">{ns}:</span>}
                    {isNs ? rest.join(':') : tag}
                  </span>
                )
              })}
            </div>

            {/* Actions */}
            <div className="flex gap-2 mt-auto pt-1">
              <button
                onClick={() => onDownload(gallery)}
                className="px-4 py-2 bg-green-700 hover:bg-green-600 rounded text-white text-sm font-medium transition-colors"
              >
                Download
              </button>
              <button
                onClick={onClose}
                className="px-4 py-2 bg-[#1a1a1a] border border-[#333] hover:border-[#555] rounded text-gray-400 text-sm transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────

type ViewMode = 'list' | 'grid'

const CATEGORIES = Object.entries(CATEGORY_META).map(([value, { color, label }]) => ({
  value,
  label,
  color,
}))

export default function BrowsePage() {
  const [inputValue, setInputValue]         = useState('')
  const [searchQuery, setSearchQuery]       = useState('')
  const [category, setCategory]             = useState<string | null>(null)
  const [page, setPage]                     = useState(0)
  const [viewMode, setViewMode]             = useState<ViewMode>('grid')
  const [selectedGallery, setSelectedGallery] = useState<EhGallery | null>(null)
  const [downloadUrl, setDownloadUrl]       = useState('')
  const [downloadSource, setDownloadSource] = useState('ehentai')
  const [downloadMsg, setDownloadMsg]       = useState<{ text: string; ok: boolean } | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data, isLoading, error } = useEhSearch({
    q: searchQuery || undefined,
    category: category || undefined,
    page,
  })

  // ── Handlers ────────────────────────────────────────────

  const commitSearch = useCallback((q: string) => {
    setSearchQuery(q)
    setPage(0)
  }, [])

  const handleInputChange = useCallback((value: string) => {
    setInputValue(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => commitSearch(value), 600)
  }, [commitSearch])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      commitSearch(inputValue)
    }
  }, [inputValue, commitSearch])

  const handleCategoryClick = useCallback((val: string | null) => {
    setCategory((prev) => (prev === val ? null : val))
    setPage(0)
  }, [])

  const handleDownload = useCallback(async (gallery: EhGallery) => {
    const url = `https://e-hentai.org/g/${gallery.gid}/${gallery.token}/`
    setDownloadMsg(null)
    try {
      const res = await api.download.enqueue(url, 'ehentai')
      setDownloadMsg({ text: `已加入佇列 (job: ${res.job_id})`, ok: true })
    } catch (err) {
      setDownloadMsg({ text: err instanceof Error ? err.message : 'Failed', ok: false })
    }
  }, [])

  const handleUrlDownload = useCallback(async () => {
    if (!downloadUrl.trim()) return
    setDownloadMsg(null)
    try {
      const res = await api.download.enqueue(downloadUrl.trim(), downloadSource)
      setDownloadMsg({ text: `已加入佇列 (job: ${res.job_id})`, ok: true })
      setDownloadUrl('')
    } catch (err) {
      setDownloadMsg({ text: err instanceof Error ? err.message : 'Failed', ok: false })
    }
  }, [downloadUrl, downloadSource])

  const totalPages = data ? Math.ceil(data.total / 25) : 0

  // ── Render ─────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-5xl mx-auto px-4 py-5 space-y-4">

        {/* ── Search bar ── */}
        <div className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search E-Hentai…"
            className="flex-1 bg-[#111] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm
                       text-white placeholder-gray-600 focus:outline-none focus:border-[#555] transition-colors"
          />
          <button
            onClick={() => { if (debounceRef.current) clearTimeout(debounceRef.current); commitSearch(inputValue) }}
            className="px-4 py-2.5 bg-[#1a6edf] hover:bg-[#1559b3] rounded-lg text-white text-sm font-medium transition-colors"
          >
            Search
          </button>
          {/* View toggle */}
          <div className="flex border border-[#2a2a2a] rounded-lg overflow-hidden">
            <button
              onClick={() => setViewMode('list')}
              title="List view"
              className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'list' ? 'bg-[#1a1a1a] text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >
              ☰
            </button>
            <button
              onClick={() => setViewMode('grid')}
              title="Grid view"
              className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'grid' ? 'bg-[#1a1a1a] text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >
              ⊞
            </button>
          </div>
        </div>

        {/* ── Category filter row ── */}
        <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
          <button
            onClick={() => handleCategoryClick(null)}
            className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              category === null
                ? 'bg-white text-black border-white'
                : 'bg-transparent text-gray-400 border-[#333] hover:border-[#555] hover:text-gray-200'
            }`}
          >
            All
          </button>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              onClick={() => handleCategoryClick(cat.value)}
              className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-all ${
                category === cat.value
                  ? 'border-transparent'
                  : 'bg-transparent text-gray-400 border-[#333] hover:text-white hover:border-transparent'
              }`}
              style={
                category === cat.value
                  ? { backgroundColor: cat.color, borderColor: cat.color, color: isLightColor(cat.color) ? '#000' : '#fff' }
                  : undefined
              }
              onMouseEnter={(e) => {
                if (category !== cat.value) {
                  e.currentTarget.style.backgroundColor = cat.color + '33'
                  e.currentTarget.style.borderColor = cat.color
                  e.currentTarget.style.color = cat.color
                }
              }}
              onMouseLeave={(e) => {
                if (category !== cat.value) {
                  e.currentTarget.style.backgroundColor = ''
                  e.currentTarget.style.borderColor = ''
                  e.currentTarget.style.color = ''
                }
              }}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* ── Status / alerts ── */}
        {downloadMsg && (
          <AlertBanner
            alerts={[downloadMsg.text]}
            onDismiss={() => setDownloadMsg(null)}
          />
        )}

        {/* ── Results header ── */}
        {data && !isLoading && (
          <div className="flex items-center justify-between text-xs text-gray-600">
            <span>{data.total.toLocaleString()} results{searchQuery && ` for "${searchQuery}"`}</span>
            <span>Page {page + 1}</span>
          </div>
        )}

        {/* ── Loading ── */}
        {isLoading && (
          <div className="flex justify-center py-20">
            <LoadingSpinner />
          </div>
        )}

        {/* ── Error ── */}
        {error && !isLoading && (
          <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
            {error.message?.includes('credentials not configured') || error.message?.includes('503') ? (
              <p className="text-yellow-400">
                E-Hentai 憑證尚未設定。請前往{' '}
                <a href="/settings" className="underline text-yellow-300 hover:text-white">Settings</a>
                {' '}輸入 EH Cookie（ipb_member_id、ipb_pass_hash、sk）。
              </p>
            ) : (
              <p className="text-red-400">{error.message || 'Failed to load results'}</p>
            )}
          </div>
        )}

        {/* ── Gallery grid / list ── */}
        {!isLoading && data && data.galleries.length > 0 && (
          <>
            {viewMode === 'list' ? (
              <div className="space-y-2">
                {data.galleries.map((g) => (
                  <ListCard key={`${g.gid}-${g.token}`} gallery={g} onClick={() => setSelectedGallery(g)} />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                {data.galleries.map((g) => (
                  <GridCard key={`${g.gid}-${g.token}`} gallery={g} onClick={() => setSelectedGallery(g)} />
                ))}
              </div>
            )}

            {totalPages > 1 && (
              <div className="pt-2">
                <Pagination page={page} total={data.total} onChange={(p) => { setPage(p); window.scrollTo(0, 0) }} />
              </div>
            )}
          </>
        )}

        {/* ── Empty state ── */}
        {!isLoading && !error && data && data.galleries.length === 0 && (
          <div className="text-center py-20 text-gray-600">
            No results found.
          </div>
        )}


        {/* ── Quick URL download ── */}
        <div className="mt-4 pt-4 border-t border-[#1a1a1a]">
          <p className="text-xs text-gray-600 uppercase tracking-wide mb-2">Quick Download by URL</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={downloadUrl}
              onChange={(e) => setDownloadUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleUrlDownload()}
              placeholder="https://e-hentai.org/g/…"
              className="flex-1 bg-[#111] border border-[#2a2a2a] rounded-lg px-3 py-2 text-white
                         placeholder-gray-700 text-sm focus:outline-none focus:border-[#444] transition-colors"
            />
            <select
              value={downloadSource}
              onChange={(e) => setDownloadSource(e.target.value)}
              className="bg-[#111] border border-[#2a2a2a] rounded-lg px-2 py-2 text-white text-sm focus:outline-none"
            >
              <option value="ehentai">E-Hentai</option>
              <option value="pixiv">Pixiv</option>
            </select>
            <button
              onClick={handleUrlDownload}
              disabled={!downloadUrl.trim()}
              className="px-4 py-2 bg-green-800 hover:bg-green-700 disabled:opacity-40 rounded-lg text-white text-sm font-medium transition-colors"
            >
              Add
            </button>
          </div>
        </div>
      </div>

      {/* ── Gallery modal ── */}
      {selectedGallery && (
        <GalleryModal
          gallery={selectedGallery}
          onClose={() => setSelectedGallery(null)}
          onDownload={(g) => { handleDownload(g); setSelectedGallery(null) }}
        />
      )}
    </div>
  )
}
