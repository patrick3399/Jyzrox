'use client'

import { useState, useRef, useCallback, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEhSearch, useEhFavorites, useEhPopular, useEhToplist } from '@/hooks/useGalleries'
import { api } from '@/lib/api'
import { Pagination } from '@/components/Pagination'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { RatingStars } from '@/components/RatingStars'
import { Search as SearchIcon, X as XIcon, ChevronDown, ChevronUp, Bookmark, BookmarkCheck } from 'lucide-react'
import type { EhGallery, Credentials, SavedSearch } from '@/lib/types'

// ── IntersectionObserver-based lazy image ──────────────────────────────

function LazyImage({ src, alt, className }: { src: string; alt: string; className: string }) {
  const [error, setError] = useState(false)

  if (error) {
    return <div className={`${className} bg-vault-input`} />
  }

  return <img src={src} alt={alt} className={className} onError={() => setError(true)} />
}

// ── Search history (localStorage) ─────────────────────────────────────

const HISTORY_KEY = 'eh_search_history'
const HISTORY_ENABLED_KEY = 'eh_search_history_enabled'
const MAX_HISTORY = 10

function getSearchHistory(): string[] {
  if (typeof window === 'undefined') return []
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    return []
  }
}

function addSearchHistory(query: string) {
  if (typeof window === 'undefined') return
  if (!query.trim()) return
  if (localStorage.getItem(HISTORY_ENABLED_KEY) === 'false') return
  const history = getSearchHistory().filter((h) => h !== query)
  history.unshift(query)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)))
}

function removeSearchHistoryItem(query: string) {
  if (typeof window === 'undefined') return
  const history = getSearchHistory().filter((h) => h !== query)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history))
}

function clearSearchHistory() {
  if (typeof window === 'undefined') return
  localStorage.removeItem(HISTORY_KEY)
}

function isSearchHistoryEnabled(): boolean {
  if (typeof window === 'undefined') return true
  return localStorage.getItem(HISTORY_ENABLED_KEY) !== 'false'
}

// ── EhViewer category colour system (Material Design, from EhUtils.kt) ──

const CATEGORY_META: Record<string, { color: string; label: string }> = {
  doujinshi: { color: '#F44336', label: 'Doujinshi' },
  manga: { color: '#FF9800', label: 'Manga' },
  artist_cg: { color: '#FBC02D', label: 'Artist CG' },
  game_cg: { color: '#4CAF50', label: 'Game CG' },
  western: { color: '#8BC34A', label: 'Western' },
  'non-h': { color: '#2196F3', label: 'Non-H' },
  image_set: { color: '#3F51B5', label: 'Image Set' },
  cosplay: { color: '#9C27B0', label: 'Cosplay' },
  asian_porn: { color: '#E91E63', label: 'Asian Porn' },
  misc: { color: '#9E9E9E', label: 'Misc' },
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
    year: 'numeric',
    month: 'short',
    day: 'numeric',
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
      className="flex gap-3 p-3 bg-vault-card border border-vault-border rounded-lg cursor-pointer
                 hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors active:bg-vault-card-hover"
    >
      {/* Thumbnail */}
      <div className="flex-shrink-0 w-[90px] h-[120px] bg-vault-input rounded overflow-hidden">
        {thumbSrc ? (
          <LazyImage src={thumbSrc} alt={gallery.title} className="w-full h-full object-cover" />
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
        <p className="text-xs text-vault-text-muted">{gallery.uploader}</p>

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
          <span className="text-xs text-vault-text-muted ml-auto">{gallery.pages}P</span>
          <span className="text-xs text-vault-text-muted">{formatDate(gallery.posted_at)}</span>
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
      className="relative aspect-[3/4] bg-vault-input rounded-lg overflow-hidden cursor-pointer
                 border border-vault-border hover:border-vault-border-hover transition-colors group"
    >
      {/* Thumbnail */}
      {thumbSrc ? (
        <LazyImage
          src={thumbSrc}
          alt={gallery.title}
          className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
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
        className="bg-vault-card border border-vault-border rounded-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto shadow-2xl"
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
                <span className="text-3xl font-bold" style={{ color }}>
                  {label[0]}
                </span>
              </div>
            )}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0 flex flex-col gap-2">
            <h2 className="text-base font-semibold text-vault-text leading-snug">
              {gallery.title}
            </h2>
            {gallery.title_jpn && (
              <p className="text-sm text-vault-text-secondary -mt-1">{gallery.title_jpn}</p>
            )}

            {/* Meta chips */}
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span
                className="px-2 py-0.5 rounded font-bold text-white uppercase tracking-wide"
                style={{ backgroundColor: color }}
              >
                {label}
              </span>
              <span className="px-2 py-0.5 rounded bg-vault-input border border-vault-border text-vault-text-secondary">
                {gallery.pages} pages
              </span>
              <span className="px-2 py-0.5 rounded bg-vault-input border border-vault-border text-vault-text-secondary">
                {formatDate(gallery.posted_at)}
              </span>
              {gallery.uploader && (
                <span className="px-2 py-0.5 rounded bg-vault-input border border-vault-border text-vault-text-secondary">
                  {gallery.uploader}
                </span>
              )}
            </div>

            {/* Rating */}
            <div className="flex items-center gap-2">
              <RatingStars rating={gallery.rating} readonly />
              <span className="text-xs text-vault-text-muted">{gallery.rating.toFixed(1)}</span>
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
                               bg-vault-input border-vault-border text-vault-text-secondary"
                  >
                    {isNs && <span className="text-vault-text-muted">{ns}:</span>}
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
                className="px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors"
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
type BrowseTab = 'search' | 'favorites' | 'popular' | 'toplist'
type LoadMode = 'pagination' | 'scroll'

// Toplist time-period IDs (EH convention)
const TOPLIST_OPTIONS: { tl: number; label: string }[] = [
  { tl: 11, label: 'browse.allTime' },
  { tl: 12, label: 'browse.pastYear' },
  { tl: 13, label: 'browse.pastMonth' },
  { tl: 14, label: 'browse.yesterday' },
]

const EH_PAGE_SIZE = 25 // EH always returns ~25 per page

const CATEGORIES = Object.entries(CATEGORY_META).map(([value, { color, label }]) => ({
  value,
  label,
  color,
}))

// Bitmask values matching backend CATEGORY_MASK
const CATEGORY_BITMASK: Record<string, number> = {
  misc: 1,
  doujinshi: 2,
  manga: 4,
  artist_cg: 8,
  game_cg: 16,
  image_set: 32,
  cosplay: 64,
  asian_porn: 128,
  'non-h': 256,
  western: 512,
}
const ALL_CATS_MASK = Object.values(CATEGORY_BITMASK).reduce((a, b) => a + b, 0) // 1023

// EH favorite category colors (from EhViewer)
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

function getLoadMode(): LoadMode {
  if (typeof window === 'undefined') return 'pagination'
  return (localStorage.getItem('browse_load_mode') as LoadMode) || 'pagination'
}

export default function BrowsePageWrapper() {
  return (
    <Suspense>
      <BrowsePage />
    </Suspense>
  )
}

function BrowsePage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const initialQ = searchParams.get('q') || ''
  const initialPage = Number(searchParams.get('page') || '0')
  const rawTab = searchParams.get('tab')
  const initialTab: BrowseTab =
    rawTab === 'favorites' || rawTab === 'popular' || rawTab === 'toplist' ? rawTab : 'search'
  const initialFavCat = searchParams.get('favcat') || 'all'
  const initialFavSearch = searchParams.get('favsearch') || ''

  const [activeTab, setActiveTab] = useState<BrowseTab>(initialTab)
  const [inputValue, setInputValue] = useState(initialQ)
  const [searchQuery, setSearchQuery] = useState(initialQ)
  const [category, setCategory] = useState<string | null>(null)
  const [page, setPage] = useState(initialPage)
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [selectedGallery, setSelectedGallery] = useState<EhGallery | null>(null)
  const [downloadUrl, setDownloadUrl] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Advanced search state
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [selectedCats, setSelectedCats] = useState<Set<string>>(new Set(Object.keys(CATEGORY_META)))
  const [advSearch, setAdvSearch] = useState(0)
  const [minRating, setMinRating] = useState<number | null>(null)
  const [pageFrom, setPageFrom] = useState<string>('')
  const [pageTo, setPageTo] = useState<string>('')

  // Favorites state (cursor-based pagination — EH favorites uses next/prev cursors, not page numbers)
  const [favCat, setFavCat] = useState<string>(initialFavCat)
  const [favCursor, setFavCursor] = useState<{ next?: string; prev?: string }>({})
  const [favSearch, setFavSearch] = useState(initialFavSearch)

  // Infinite scroll state
  const [loadMode] = useState<LoadMode>(getLoadMode)
  const [scrollGalleries, setScrollGalleries] = useState<EhGallery[]>([])
  const [scrollPage, setScrollPage] = useState(0)
  const [scrollLoading, setScrollLoading] = useState(false)
  const [scrollHasMore, setScrollHasMore] = useState(true)
  const scrollSentinelRef = useRef<HTMLDivElement>(null)
  // Same for favorites scroll (cursor-based)
  const [favScrollGalleries, setFavScrollGalleries] = useState<EhGallery[]>([])
  const [favScrollNextCursor, setFavScrollNextCursor] = useState<string | undefined>(undefined)
  const [favScrollLoading, setFavScrollLoading] = useState(false)
  const [favScrollHasMore, setFavScrollHasMore] = useState(true)
  const favScrollSentinelRef = useRef<HTMLDivElement>(null)

  // Toplist state
  const [toplistTl, setToplistTl] = useState(11)
  const [toplistPage, setToplistPage] = useState(0)

  // Saved searches state
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([])
  const [showSavedSearches, setShowSavedSearches] = useState(false)
  const [saveSearchName, setSaveSearchName] = useState('')
  const [showSaveInput, setShowSaveInput] = useState(false)
  const savedSearchesRef = useRef<HTMLDivElement>(null)

  // Search history
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState<string[]>([])
  const searchBoxRef = useRef<HTMLDivElement>(null)

  // Mobile search expand
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const mobileInputRef = useRef<HTMLInputElement>(null)

  // EH credentials (for favorites tab)
  const [ehConfigured, setEhConfigured] = useState(false)
  useEffect(() => {
    api.settings
      .getCredentials()
      .then((c: Credentials) => setEhConfigured(c.ehentai.configured))
      .catch(() => {})
  }, [])

  // Load saved searches
  const refreshSavedSearches = useCallback(() => {
    api.savedSearches
      .list()
      .then((r) => setSavedSearches(r.searches))
      .catch(() => {})
  }, [])

  useEffect(() => {
    refreshSavedSearches()
  }, [refreshSavedSearches])

  // Close saved searches dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (savedSearchesRef.current && !savedSearchesRef.current.contains(e.target as Node)) {
        setShowSavedSearches(false)
        setShowSaveInput(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Load history on focus
  const refreshHistory = useCallback(() => {
    if (isSearchHistoryEnabled()) setHistory(getSearchHistory())
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setShowHistory(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Sync URL ?q= changes (e.g. from tag clicks in detail page)
  // Only react to the q param itself, not to other searchParams changes (page, tab, etc.)
  // to avoid a feedback loop where the URL sync effect resets page to 0.
  const urlQ = searchParams.get('q') || ''
  useEffect(() => {
    if (urlQ !== searchQuery) {
      setInputValue(urlQ)
      setSearchQuery(urlQ)
      setPage(0)
    }
  }, [urlQ]) // eslint-disable-line react-hooks/exhaustive-deps

  // Persist browse state in URL so back-navigation restores it
  const isFirstRender = useRef(true)
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    const params = new URLSearchParams()
    if (searchQuery) params.set('q', searchQuery)
    if (page > 0) params.set('page', String(page))
    if (activeTab !== 'search') params.set('tab', activeTab)
    if (activeTab === 'favorites' && favCat !== 'all') params.set('favcat', favCat)
    if (activeTab === 'favorites' && favSearch) params.set('favsearch', favSearch)
    if (activeTab === 'toplist' && toplistTl !== 11) params.set('tl', String(toplistTl))
    if (activeTab === 'toplist' && toplistPage > 0) params.set('tlpage', String(toplistPage))
    const qs = params.toString()
    router.replace(qs ? `/browse?${qs}` : '/browse', { scroll: false })
  }, [searchQuery, page, activeTab, favCat, favSearch, toplistTl, toplistPage]) // eslint-disable-line react-hooks/exhaustive-deps

  // Compute f_cats bitmask from selected categories (multi-select)
  const computedFCats = (() => {
    if (!showAdvanced) {
      // Legacy single-category mode
      if (category && CATEGORY_BITMASK[category] !== undefined) {
        return ALL_CATS_MASK ^ CATEGORY_BITMASK[category]
      }
      return undefined
    }
    // Multi-select: f_cats = ALL ^ selected_mask
    if (selectedCats.size === Object.keys(CATEGORY_META).length) return undefined // all selected = no filter
    let selectedMask = 0
    for (const cat of selectedCats) {
      selectedMask |= CATEGORY_BITMASK[cat] ?? 0
    }
    return ALL_CATS_MASK ^ selectedMask
  })()

  const { data, isLoading, error } = useEhSearch({
    q: searchQuery || undefined,
    page,
    ...(showAdvanced
      ? {
          f_cats: computedFCats,
          advance: advSearch !== 0 || minRating !== null || pageFrom !== '' || pageTo !== '',
          adv_search: advSearch || undefined,
          min_rating: minRating || undefined,
          page_from: pageFrom ? Number(pageFrom) : undefined,
          page_to: pageTo ? Number(pageTo) : undefined,
        }
      : {
          category: category || undefined,
        }),
  })

  const {
    data: favData,
    isLoading: favLoading,
    error: favError,
  } = useEhFavorites(
    { favcat: favCat, q: favSearch || undefined, ...favCursor },
    activeTab === 'favorites' && ehConfigured,
  )

  const {
    data: popularData,
    isLoading: popularLoading,
    error: popularError,
  } = useEhPopular()

  const {
    data: toplistData,
    isLoading: toplistLoading,
    error: toplistError,
  } = useEhToplist(toplistTl, toplistPage)

  // Restore scroll position after back-navigation (once data is loaded)
  const scrollRestoredRef = useRef(false)
  useEffect(() => {
    if (scrollRestoredRef.current) return
    const hasData = activeTab === 'search' ? !!data : !!favData
    if (!hasData) return
    const savedY = sessionStorage.getItem('browse_scrollY')
    if (savedY) {
      scrollRestoredRef.current = true
      sessionStorage.removeItem('browse_scrollY')
      requestAnimationFrame(() => {
        window.scrollTo(0, Number(savedY))
      })
    } else {
      scrollRestoredRef.current = true
    }
  }, [data, favData, activeTab])

  // ── Infinite scroll: reset when search changes ─────────
  useEffect(() => {
    if (loadMode === 'scroll') {
      setScrollGalleries([])
      setScrollPage(0)
      setScrollHasMore(true)
    }
  }, [searchQuery, category, loadMode, advSearch, minRating, pageFrom, pageTo, selectedCats.size])

  // Append search results in scroll mode
  useEffect(() => {
    if (loadMode !== 'scroll' || !data || activeTab !== 'search') return
    setScrollGalleries((prev) => {
      if (scrollPage === 0) return data.galleries
      const existingIds = new Set(prev.map((g) => g.gid))
      const newOnes = data.galleries.filter((g) => !existingIds.has(g.gid))
      return [...prev, ...newOnes]
    })
    setScrollHasMore(data.galleries.length >= EH_PAGE_SIZE)
    setScrollLoading(false)
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset favorites scroll when filters change
  useEffect(() => {
    if (loadMode === 'scroll') {
      setFavScrollGalleries([])
      setFavScrollNextCursor(undefined)
      setFavScrollHasMore(true)
    }
  }, [favCat, favSearch, loadMode])

  // Append favorites results in scroll mode
  useEffect(() => {
    if (loadMode !== 'scroll' || !favData || activeTab !== 'favorites') return
    setFavScrollGalleries((prev) => {
      if (!favCursor.next && !favCursor.prev) return favData.galleries
      const existingIds = new Set(prev.map((g) => g.gid))
      const newOnes = favData.galleries.filter((g) => !existingIds.has(g.gid))
      return [...prev, ...newOnes]
    })
    setFavScrollHasMore(favData.has_next)
    setFavScrollNextCursor(favData.next_cursor ?? undefined)
    setFavScrollLoading(false)
  }, [favData]) // eslint-disable-line react-hooks/exhaustive-deps

  // Intersection observer for search infinite scroll
  useEffect(() => {
    if (loadMode !== 'scroll' || activeTab !== 'search') return
    const sentinel = scrollSentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && scrollHasMore && !scrollLoading && !isLoading) {
          setScrollLoading(true)
          setScrollPage((p) => p + 1)
          setPage((p) => p + 1)
        }
      },
      { rootMargin: '400px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMode, activeTab, scrollHasMore, scrollLoading, isLoading])

  // Intersection observer for favorites infinite scroll (cursor-based)
  useEffect(() => {
    if (loadMode !== 'scroll' || activeTab !== 'favorites') return
    const sentinel = favScrollSentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries[0].isIntersecting &&
          favScrollHasMore &&
          !favScrollLoading &&
          !favLoading &&
          favScrollNextCursor
        ) {
          setFavScrollLoading(true)
          setFavCursor({ next: favScrollNextCursor })
        }
      },
      { rootMargin: '400px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMode, activeTab, favScrollHasMore, favScrollLoading, favLoading, favScrollNextCursor])

  // ── Handlers ────────────────────────────────────────────

  const commitSearch = useCallback((q: string) => {
    addSearchHistory(q)
    setSearchQuery(q)
    setPage(0)
    setScrollGalleries([])
    setScrollPage(0)
    setScrollHasMore(true)
    setShowHistory(false)
  }, [])

  const handleInputChange = useCallback(
    (value: string) => {
      setInputValue(value)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => commitSearch(value), 600)
    },
    [commitSearch],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        commitSearch(inputValue)
      } else if (e.key === 'Escape') {
        setShowHistory(false)
      }
    },
    [inputValue, commitSearch],
  )

  const handleHistorySelect = useCallback(
    (q: string) => {
      setInputValue(q)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      commitSearch(q)
    },
    [commitSearch],
  )

  const handleHistoryRemove = useCallback((q: string, e: React.MouseEvent) => {
    e.stopPropagation()
    removeSearchHistoryItem(q)
    setHistory(getSearchHistory())
  }, [])

  const handleCategoryClick = useCallback(
    (val: string | null) => {
      if (showAdvanced) {
        // Multi-select toggle
        if (val === null) {
          // "All" button: select all
          setSelectedCats(new Set(Object.keys(CATEGORY_META)))
        } else {
          setSelectedCats((prev) => {
            const next = new Set(prev)
            if (next.has(val)) next.delete(val)
            else next.add(val)
            return next
          })
        }
      } else {
        setCategory((prev) => (prev === val ? null : val))
      }
      setPage(0)
    },
    [showAdvanced],
  )

  const navigateToGallery = useCallback(
    (g: EhGallery) => {
      sessionStorage.setItem('browse_scrollY', String(window.scrollY))
      router.push(`/browse/${g.gid}/${g.token}`)
    },
    [router],
  )

  const handleDownload = useCallback(async (gallery: EhGallery) => {
    const url = `https://e-hentai.org/g/${gallery.gid}/${gallery.token}/`
    try {
      const res = await api.download.enqueue(url, 'ehentai', {}, gallery.pages)
      toast.success(`已加入佇列 (job: ${res.job_id})`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }, [])

  const handleUrlDownload = useCallback(async () => {
    if (!downloadUrl.trim()) return
    try {
      const res = await api.download.enqueue(downloadUrl.trim())
      toast.success(`已加入佇列 (job: ${res.job_id})`)
      setDownloadUrl('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed')
    }
  }, [downloadUrl])

  const handleSaveSearch = useCallback(async () => {
    const name = saveSearchName.trim() || searchQuery || 'Search'
    try {
      await api.savedSearches.create({ name, query: searchQuery, params: {} })
      toast.success(t('browse.saveSearchSaved'))
      setSaveSearchName('')
      setShowSaveInput(false)
      refreshSavedSearches()
    } catch {
      toast.error(t('browse.saveSearchFailed'))
    }
  }, [saveSearchName, searchQuery, refreshSavedSearches])

  const handleDeleteSavedSearch = useCallback(
    async (id: number, e: React.MouseEvent) => {
      e.stopPropagation()
      try {
        await api.savedSearches.delete(id)
        toast.success(t('browse.saveSearchDeleted'))
        refreshSavedSearches()
      } catch {
        toast.error(t('browse.saveSearchDeleteFailed'))
      }
    },
    [refreshSavedSearches],
  )

  const handleLoadSavedSearch = useCallback(
    (s: SavedSearch) => {
      setInputValue(s.query)
      commitSearch(s.query)
      setActiveTab('search')
      setShowSavedSearches(false)
    },
    [commitSearch],
  )

  const displayGalleries = loadMode === 'scroll' ? scrollGalleries : (data?.galleries ?? [])
  const favDisplayGalleries =
    loadMode === 'scroll' ? favScrollGalleries : (favData?.galleries ?? [])
  const totalPages = data ? Math.ceil(data.total / EH_PAGE_SIZE) : 0

  // ── Render ─────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-vault-bg text-vault-text">
      <div className="max-w-5xl mx-auto px-4 py-5 space-y-4">
        {/* ── Search bar with history dropdown ── */}

        {/* Mobile: expanded search overlay */}
        {mobileSearchOpen && (
          <div className="sm:hidden flex gap-2">
            <div ref={searchBoxRef} className="relative flex-1">
              <input
                ref={mobileInputRef}
                type="text"
                value={inputValue}
                onChange={(e) => handleInputChange(e.target.value)}
                onKeyDown={(e) => {
                  handleKeyDown(e)
                  if (e.key === 'Enter') setMobileSearchOpen(false)
                }}
                onFocus={() => {
                  refreshHistory()
                  setShowHistory(true)
                }}
                placeholder={t('browse.searchPlaceholder')}
                autoFocus
                className="w-full bg-vault-card border border-vault-border rounded-lg px-4 py-2.5 text-sm
                           text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors"
              />

              {/* History dropdown */}
              {showHistory && history.length > 0 && (
                <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden max-h-[min(320px,50vh)]">
                  <div className="flex items-center justify-between px-3 py-1.5 border-b border-vault-border">
                    <span className="text-[11px] text-vault-text-muted uppercase tracking-wide">
                      {t('browse.recent')}
                    </span>
                    <button
                      onClick={() => {
                        clearSearchHistory()
                        setHistory([])
                      }}
                      className="text-[11px] text-vault-text-muted hover:text-red-400 transition-colors"
                    >
                      {t('browse.clearAll')}
                    </button>
                  </div>
                  {history.map((q) => (
                    <button
                      key={q}
                      onClick={() => {
                        handleHistorySelect(q)
                        setMobileSearchOpen(false)
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-vault-text
                                 hover:bg-vault-card-hover transition-colors group"
                    >
                      <span className="text-vault-text-muted text-xs">&#x1F50D;</span>
                      <span className="flex-1 truncate">{q}</span>
                      <span
                        onClick={(e) => handleHistoryRemove(q, e)}
                        className="text-vault-text-muted hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity px-1"
                        title="Remove"
                      >
                        ✕
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => {
                setMobileSearchOpen(false)
                setShowHistory(false)
              }}
              className="px-3 py-2.5 text-sm text-vault-text-secondary hover:text-vault-text transition-colors shrink-0"
            >
              <XIcon size={18} />
            </button>
          </div>
        )}

        {/* Desktop + mobile compact row */}
        <div className={`flex gap-2 ${mobileSearchOpen ? 'hidden sm:flex' : ''}`}>
          {/* Mobile search icon button */}
          <button
            onClick={() => setMobileSearchOpen(true)}
            className="sm:hidden p-2.5 bg-vault-card border border-vault-border rounded-lg text-vault-text-secondary hover:text-vault-text transition-colors shrink-0"
            aria-label={t('browse.search')}
          >
            <SearchIcon size={18} />
          </button>

          {/* Desktop search input */}
          <div
            ref={!mobileSearchOpen ? searchBoxRef : undefined}
            className="relative flex-1 hidden sm:block"
          >
            <input
              type="text"
              value={inputValue}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => {
                refreshHistory()
                setShowHistory(true)
              }}
              placeholder={t('browse.searchPlaceholder')}
              className="w-full bg-vault-card border border-vault-border rounded-lg px-4 py-2.5 text-sm
                         text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors"
            />

            {/* History dropdown */}
            {showHistory && history.length > 0 && (
              <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden max-h-[min(320px,50vh)]">
                <div className="flex items-center justify-between px-3 py-1.5 border-b border-vault-border">
                  <span className="text-[11px] text-vault-text-muted uppercase tracking-wide">
                    {t('browse.recent')}
                  </span>
                  <button
                    onClick={() => {
                      clearSearchHistory()
                      setHistory([])
                    }}
                    className="text-[11px] text-vault-text-muted hover:text-red-400 transition-colors"
                  >
                    {t('browse.clearAll')}
                  </button>
                </div>
                {history.map((q) => (
                  <button
                    key={q}
                    onClick={() => handleHistorySelect(q)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-vault-text
                               hover:bg-vault-card-hover transition-colors group"
                  >
                    <span className="text-vault-text-muted text-xs">&#x1F50D;</span>
                    <span className="flex-1 truncate">{q}</span>
                    <span
                      onClick={(e) => handleHistoryRemove(q, e)}
                      className="text-vault-text-muted hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity px-1"
                      title="Remove"
                    >
                      ✕
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={() => {
              if (debounceRef.current) clearTimeout(debounceRef.current)
              commitSearch(inputValue)
            }}
            className="hidden sm:block px-4 py-2.5 bg-vault-accent hover:bg-vault-accent/90 rounded-lg text-white text-sm font-medium transition-colors shrink-0"
          >
            {t('browse.search')}
          </button>

          {/* Saved Searches button (desktop) */}
          <div ref={savedSearchesRef} className="relative hidden sm:block shrink-0">
            <button
              onClick={() => {
                setShowSavedSearches((v) => !v)
                setShowSaveInput(false)
              }}
              title={t('browse.savedSearches')}
              className="p-2.5 bg-vault-card border border-vault-border rounded-lg text-vault-text-secondary hover:text-vault-text transition-colors"
            >
              {savedSearches.length > 0 ? <BookmarkCheck size={18} /> : <Bookmark size={18} />}
            </button>

            {/* Saved searches dropdown */}
            {showSavedSearches && (
              <div className="absolute right-0 top-full mt-1 z-30 w-64 bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-vault-border">
                  <span className="text-xs font-medium text-vault-text">
                    {t('browse.savedSearches')}
                  </span>
                  {searchQuery && (
                    <button
                      onClick={() => setShowSaveInput((v) => !v)}
                      className="text-xs text-vault-accent hover:text-vault-accent/80 transition-colors"
                    >
                      {t('browse.saveSearch')}
                    </button>
                  )}
                </div>

                {/* Save current search input */}
                {showSaveInput && searchQuery && (
                  <div className="px-3 py-2 border-b border-vault-border flex gap-2">
                    <input
                      type="text"
                      value={saveSearchName}
                      onChange={(e) => setSaveSearchName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSaveSearch()}
                      placeholder={t('browse.saveSearchName')}
                      autoFocus
                      className="flex-1 min-w-0 bg-vault-input border border-vault-border rounded px-2 py-1 text-xs text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent"
                    />
                    <button
                      onClick={handleSaveSearch}
                      className="px-2 py-1 bg-vault-accent hover:bg-vault-accent/80 rounded text-white text-xs font-medium transition-colors shrink-0"
                    >
                      {t('browse.saveSearch')}
                    </button>
                  </div>
                )}

                {/* List of saved searches */}
                <div className="max-h-60 overflow-y-auto">
                  {savedSearches.length === 0 ? (
                    <p className="px-3 py-4 text-xs text-vault-text-muted text-center">
                      {t('browse.noSavedSearches')}
                    </p>
                  ) : (
                    savedSearches.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => handleLoadSavedSearch(s)}
                        className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-vault-text hover:bg-vault-card-hover transition-colors group"
                      >
                        <span className="flex-1 truncate text-xs">{s.name}</span>
                        {s.query && (
                          <span className="text-[10px] text-vault-text-muted truncate max-w-[80px]">
                            {s.query}
                          </span>
                        )}
                        <span
                          onClick={(e) => handleDeleteSavedSearch(s.id, e)}
                          className="text-vault-text-muted hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity px-1 shrink-0"
                          title="Delete"
                        >
                          ✕
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
          {/* View toggle */}
          <div className="flex border border-vault-border rounded-lg overflow-hidden shrink-0">
            <button
              onClick={() => setViewMode('list')}
              title="List view"
              className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'list' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
            >
              ☰
            </button>
            <button
              onClick={() => setViewMode('grid')}
              title="Grid view"
              className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'grid' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
            >
              ⊞
            </button>
          </div>
        </div>

        {/* ── Tab switcher ── */}
        <div className="flex gap-1 border-b border-vault-border overflow-x-auto scrollbar-hide">
          <button
            onClick={() => {
              setActiveTab('search')
              setPage(0)
            }}
            className={`flex-shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'search'
                ? 'border-vault-accent text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.searchTab')}
          </button>
          {ehConfigured && (
            <button
              onClick={() => {
                setActiveTab('favorites')
                setFavCursor({})
              }}
              className={`flex-shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'favorites'
                  ? 'border-[#e91e63] text-vault-text'
                  : 'border-transparent text-vault-text-muted hover:text-vault-text'
              }`}
            >
              {t('browse.favoritesTab')}
            </button>
          )}
          <button
            onClick={() => setActiveTab('popular')}
            className={`flex-shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'popular'
                ? 'border-orange-400 text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.popularTab')}
          </button>
          <button
            onClick={() => {
              setActiveTab('toplist')
              setToplistPage(0)
            }}
            className={`flex-shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'toplist'
                ? 'border-yellow-400 text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.toplistTab')}
          </button>
        </div>

        {/* ════════ SEARCH TAB ════════ */}
        {activeTab === 'search' && (
          <>
            {/* ── Category filter row ── */}
            <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
              <button
                onClick={() => handleCategoryClick(null)}
                className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  (!showAdvanced && category === null) ||
                  (showAdvanced && selectedCats.size === Object.keys(CATEGORY_META).length)
                    ? 'bg-vault-text text-vault-bg border-vault-text'
                    : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
                }`}
              >
                {t('common.all')}
              </button>
              {CATEGORIES.map((cat) => {
                const isActive = showAdvanced ? selectedCats.has(cat.value) : category === cat.value
                return (
                  <button
                    key={cat.value}
                    onClick={() => handleCategoryClick(cat.value)}
                    className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-all ${
                      isActive
                        ? 'border-transparent'
                        : 'bg-transparent text-vault-text-secondary border-vault-border hover:text-white hover:border-transparent'
                    }`}
                    style={
                      isActive
                        ? {
                            backgroundColor: cat.color,
                            borderColor: cat.color,
                            color: isLightColor(cat.color) ? '#000' : '#fff',
                          }
                        : undefined
                    }
                    onMouseEnter={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.backgroundColor = cat.color + '33'
                        e.currentTarget.style.borderColor = cat.color
                        e.currentTarget.style.color = cat.color
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.backgroundColor = ''
                        e.currentTarget.style.borderColor = ''
                        e.currentTarget.style.color = ''
                      }
                    }}
                  >
                    {cat.label}
                  </button>
                )
              })}
            </div>

            {/* ── Advanced Search toggle + panel ── */}
            <div>
              <button
                onClick={() => setShowAdvanced((v) => !v)}
                className="flex items-center gap-1 text-xs text-vault-text-muted hover:text-vault-text transition-colors"
              >
                Advanced Search
                {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>

              {showAdvanced && (
                <div className="mt-2 bg-vault-card border border-vault-border rounded-lg p-4 space-y-4">
                  {/* Search in */}
                  <div>
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                      Search in
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {[
                        { bit: 0x1, label: 'Name' },
                        { bit: 0x2, label: 'Tags' },
                        { bit: 0x4, label: 'Description' },
                        { bit: 0x8, label: 'Torrent Filenames' },
                        { bit: 0x10, label: 'Only Torrents' },
                      ].map(({ bit, label }) => (
                        <label
                          key={bit}
                          className="flex items-center gap-1.5 text-xs text-vault-text-secondary cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={!!(advSearch & bit)}
                            onChange={() => setAdvSearch((v) => v ^ bit)}
                            className="rounded border-vault-border"
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Filters */}
                  <div>
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                      Filters
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {[
                        { bit: 0x20, label: 'Show Expunged' },
                        { bit: 0x100, label: 'Disable Language Filter' },
                        { bit: 0x200, label: 'Disable Uploader Filter' },
                        { bit: 0x400, label: 'Disable Tag Filter' },
                      ].map(({ bit, label }) => (
                        <label
                          key={bit}
                          className="flex items-center gap-1.5 text-xs text-vault-text-secondary cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={!!(advSearch & bit)}
                            onChange={() => setAdvSearch((v) => v ^ bit)}
                            className="rounded border-vault-border"
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Min Rating + Page Range */}
                  <div className="flex flex-wrap gap-4">
                    <div>
                      <p className="text-xs text-vault-text-muted mb-1">Minimum Rating</p>
                      <select
                        value={minRating ?? ''}
                        onChange={(e) =>
                          setMinRating(e.target.value ? Number(e.target.value) : null)
                        }
                        className="bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                      >
                        <option value="">Any</option>
                        <option value="2">2+</option>
                        <option value="3">3+</option>
                        <option value="4">4+</option>
                        <option value="5">5</option>
                      </select>
                    </div>
                    <div>
                      <p className="text-xs text-vault-text-muted mb-1">Page Range</p>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          value={pageFrom}
                          onChange={(e) => setPageFrom(e.target.value)}
                          placeholder="From"
                          className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                        />
                        <span className="text-vault-text-muted text-xs">-</span>
                        <input
                          type="number"
                          value={pageTo}
                          onChange={(e) => setPageTo(e.target.value)}
                          placeholder="To"
                          className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Reset */}
                  <button
                    onClick={() => {
                      setAdvSearch(0)
                      setMinRating(null)
                      setPageFrom('')
                      setPageTo('')
                      setSelectedCats(new Set(Object.keys(CATEGORY_META)))
                    }}
                    className="text-xs text-vault-text-muted hover:text-vault-text transition-colors"
                  >
                    Reset Advanced
                  </button>
                </div>
              )}
            </div>

            {/* ── Results header ── */}
            {data && !isLoading && (
              <div className="flex items-center justify-between text-xs text-vault-text-muted">
                <span>
                  {data.total.toLocaleString()} results{searchQuery && ` for "${searchQuery}"`}
                </span>
                <div className="flex items-center gap-2">
                  {searchQuery && (
                    <button
                      onClick={() => {
                        setShowSaveInput(true)
                        setShowSavedSearches(true)
                      }}
                      className="flex items-center gap-1 text-vault-text-muted hover:text-vault-accent transition-colors"
                      title={t('browse.saveSearch')}
                    >
                      <Bookmark size={12} />
                      {t('browse.saveSearch')}
                    </button>
                  )}
                  <span>Page {page + 1}</span>
                </div>
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
                {error.message?.includes('credentials not configured') ||
                error.message?.includes('503') ? (
                  <p className="text-yellow-400">
                    E-Hentai 憑證尚未設定。請前往{' '}
                    <a href="/settings" className="underline text-yellow-300 hover:text-white">
                      Settings
                    </a>{' '}
                    輸入 EH Cookie（ipb_member_id、ipb_pass_hash、sk）。
                  </p>
                ) : (
                  <p className="text-red-400">{error.message || 'Failed to load results'}</p>
                )}
              </div>
            )}

            {/* ── Gallery grid / list ── */}
            {displayGalleries.length > 0 && (
              <>
                {viewMode === 'list' ? (
                  <div className="space-y-2">
                    {displayGalleries.map((g) => (
                      <ListCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                    {displayGalleries.map((g) => (
                      <GridCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                )}

                {/* Pagination mode */}
                {loadMode === 'pagination' && totalPages > 1 && (
                  <div className="pt-2">
                    <Pagination
                      page={page}
                      total={data?.total ?? 0}
                      pageSize={EH_PAGE_SIZE}
                      onChange={(p) => {
                        setPage(p)
                        window.scrollTo(0, 0)
                      }}
                    />
                  </div>
                )}

                {/* Infinite scroll sentinel */}
                {loadMode === 'scroll' && (
                  <div ref={scrollSentinelRef} className="flex justify-center py-4">
                    {(scrollLoading || isLoading) && <LoadingSpinner />}
                    {!scrollHasMore && (
                      <span className="text-xs text-vault-text-muted">
                        {t('browse.noMoreResults')}
                      </span>
                    )}
                  </div>
                )}
              </>
            )}

            {/* ── Empty state ── */}
            {!isLoading && !error && data && displayGalleries.length === 0 && (
              <div className="text-center py-20 text-vault-text-muted">{t('browse.noResults')}</div>
            )}
          </>
        )}

        {/* ════════ FAVORITES TAB ════════ */}
        {activeTab === 'favorites' && ehConfigured && (
          <>
            {/* ── Favorites category pills (All + 0-9) ── */}
            <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
              <button
                onClick={() => {
                  setFavCat('all')
                  setFavCursor({})
                  setFavScrollGalleries([])
                  setFavScrollNextCursor(undefined)
                  setFavScrollHasMore(true)
                }}
                className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  favCat === 'all'
                    ? 'bg-vault-text text-vault-bg border-vault-text'
                    : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
                }`}
              >
                {t('common.all')}
              </button>
              {Array.from({ length: 10 }, (_, i) => {
                const catData = favData?.categories?.find((c) => c.index === i)
                const name = catData?.name || `Favorites ${i}`
                const count = catData?.count
                const color = FAV_COLORS[i]
                const isActive = favCat === String(i)
                return (
                  <button
                    key={i}
                    onClick={() => {
                      setFavCat(String(i))
                      setFavCursor({})
                      setFavScrollGalleries([])
                      setFavScrollNextCursor(undefined)
                      setFavScrollHasMore(true)
                    }}
                    className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                      isActive
                        ? 'text-white border-transparent'
                        : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
                    }`}
                    style={isActive ? { backgroundColor: color, borderColor: color } : undefined}
                  >
                    {name}
                  </button>
                )
              })}
            </div>

            {/* Favorites search */}
            <input
              type="text"
              value={favSearch}
              onChange={(e) => {
                setFavSearch(e.target.value)
                setFavCursor({})
              }}
              placeholder={t('browse.filterFavorites')}
              className="w-full bg-vault-card border border-vault-border rounded-lg px-4 py-2 text-sm
                     text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors"
            />

            {/* Favorites results header */}
            {favData && !favLoading && (
              <div className="flex items-center justify-between text-xs text-vault-text-muted">
                <span>
                  {favData.total.toLocaleString()} favorited
                  {favSearch && ` matching "${favSearch}"`}
                </span>
              </div>
            )}

            {/* Favorites loading */}
            {favLoading && (
              <div className="flex justify-center py-20">
                <LoadingSpinner />
              </div>
            )}

            {/* Favorites error */}
            {favError && !favLoading && (
              <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
                <p className="text-red-400">{favError.message || 'Failed to load favorites'}</p>
              </div>
            )}

            {/* Favorites gallery grid / list */}
            {favDisplayGalleries.length > 0 && (
              <>
                {viewMode === 'list' ? (
                  <div className="space-y-2">
                    {favDisplayGalleries.map((g) => (
                      <ListCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                    {favDisplayGalleries.map((g) => (
                      <GridCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                )}

                {/* Pagination mode — cursor-based prev/next */}
                {loadMode === 'pagination' && (favData?.has_prev || favData?.has_next) && (
                  <div className="flex justify-center gap-4 pt-2">
                    <button
                      disabled={!favData?.has_prev}
                      onClick={() => {
                        if (favData?.prev_cursor) {
                          setFavCursor({ prev: favData.prev_cursor })
                          window.scrollTo(0, 0)
                        }
                      }}
                      className="rounded-lg bg-vault-card border border-vault-border px-4 py-2 text-sm text-vault-text
                             hover:bg-vault-card-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      {t('common.prev')}
                    </button>
                    <button
                      disabled={!favData?.has_next}
                      onClick={() => {
                        if (favData?.next_cursor) {
                          setFavCursor({ next: favData.next_cursor })
                          window.scrollTo(0, 0)
                        }
                      }}
                      className="rounded-lg bg-vault-card border border-vault-border px-4 py-2 text-sm text-vault-text
                             hover:bg-vault-card-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      {t('common.next')}
                    </button>
                  </div>
                )}

                {/* Infinite scroll sentinel */}
                {loadMode === 'scroll' && (
                  <div ref={favScrollSentinelRef} className="flex justify-center py-4">
                    {(favScrollLoading || favLoading) && <LoadingSpinner />}
                    {!favScrollHasMore && (
                      <span className="text-xs text-vault-text-muted">
                        {t('browse.noMoreFavorites')}
                      </span>
                    )}
                  </div>
                )}
              </>
            )}

            {/* Favorites empty */}
            {!favLoading && !favError && favData && favDisplayGalleries.length === 0 && (
              <div className="text-center py-20 text-vault-text-muted">
                {t('browse.noFavorites')}
              </div>
            )}
          </>
        )}

        {/* ════════ POPULAR TAB ════════ */}
        {activeTab === 'popular' && (
          <>
            {popularLoading && (
              <div className="flex justify-center py-20">
                <LoadingSpinner />
              </div>
            )}

            {popularError && !popularLoading && (
              <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
                <p className="text-red-400">{popularError.message || 'Failed to load popular'}</p>
              </div>
            )}

            {popularData && !popularLoading && (
              <>
                <div className="text-xs text-vault-text-muted">
                  {popularData.galleries.length} {t('browse.results')}
                </div>

                {viewMode === 'list' ? (
                  <div className="space-y-2">
                    {popularData.galleries.map((g) => (
                      <ListCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                    {popularData.galleries.map((g) => (
                      <GridCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                )}
              </>
            )}

            {!popularLoading && !popularError && popularData?.galleries.length === 0 && (
              <div className="text-center py-20 text-vault-text-muted">{t('common.noResults')}</div>
            )}
          </>
        )}

        {/* ════════ TOPLIST TAB ════════ */}
        {activeTab === 'toplist' && (
          <>
            {/* Time-period sub-filter */}
            <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
              {TOPLIST_OPTIONS.map(({ tl, label }) => (
                <button
                  key={tl}
                  onClick={() => {
                    setToplistTl(tl)
                    setToplistPage(0)
                  }}
                  className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                    toplistTl === tl
                      ? 'bg-yellow-500 text-black border-yellow-500'
                      : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
                  }`}
                >
                  {t(label)}
                </button>
              ))}
            </div>

            {toplistLoading && (
              <div className="flex justify-center py-20">
                <LoadingSpinner />
              </div>
            )}

            {toplistError && !toplistLoading && (
              <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
                <p className="text-red-400">{toplistError.message || 'Failed to load top lists'}</p>
              </div>
            )}

            {toplistData && !toplistLoading && (
              <>
                <div className="flex items-center justify-between text-xs text-vault-text-muted">
                  <span>
                    {toplistData.total.toLocaleString()} {t('browse.results')}
                  </span>
                  <span>
                    {t('browse.page')} {toplistPage + 1}
                  </span>
                </div>

                {viewMode === 'list' ? (
                  <div className="space-y-2">
                    {toplistData.galleries.map((g) => (
                      <ListCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                    {toplistData.galleries.map((g) => (
                      <GridCard
                        key={`${g.gid}-${g.token}`}
                        gallery={g}
                        onClick={() => navigateToGallery(g)}
                      />
                    ))}
                  </div>
                )}

                {/* Toplist pagination */}
                {toplistData.galleries.length > 0 && (
                  <div className="pt-2">
                    <Pagination
                      page={toplistPage}
                      total={toplistData.total}
                      pageSize={EH_PAGE_SIZE}
                      onChange={(p) => {
                        setToplistPage(p)
                        window.scrollTo(0, 0)
                      }}
                    />
                  </div>
                )}
              </>
            )}

            {!toplistLoading && !toplistError && toplistData?.galleries.length === 0 && (
              <div className="text-center py-20 text-vault-text-muted">{t('common.noResults')}</div>
            )}
          </>
        )}

        {/* ── Quick URL download ── */}
        <div className="mt-4 pt-4 border-t border-vault-border">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('browse.quickDownload')}
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={downloadUrl}
              onChange={(e) => setDownloadUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleUrlDownload()}
              placeholder="https://e-hentai.org/g/…"
              className="flex-1 bg-vault-card border border-vault-border rounded-lg px-3 py-2 text-vault-text
                         placeholder-vault-text-muted text-sm focus:outline-none focus:border-vault-accent transition-colors"
            />
            <button
              onClick={handleUrlDownload}
              disabled={!downloadUrl.trim()}
              className="px-4 py-2 bg-green-800 hover:bg-green-700 disabled:opacity-40 rounded-lg text-white text-sm font-medium transition-colors"
            >
              {t('browse.add')}
            </button>
          </div>
        </div>
      </div>

      {/* Gallery modal kept for quick-action fallback (e.g. long-press in future) */}
    </div>
  )
}
