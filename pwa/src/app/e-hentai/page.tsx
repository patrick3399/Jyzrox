'use client'

import { useState, useRef, useCallback, useEffect, useMemo, Suspense } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEhSearch, useEhFavorites, useEhPopular, useEhToplist } from '@/hooks/useGalleries'
import { useCreateSubscription } from '@/hooks/useSubscriptions'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'

import { LoadingSpinner } from '@/components/LoadingSpinner'
import { VirtualGrid } from '@/components/VirtualGrid'
import { CredentialBanner } from '@/components/CredentialBanner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { RatingStars } from '@/components/RatingStars'
import Paginator from '@/components/Paginator'
import {
  Search as SearchIcon,
  X as XIcon,
  ChevronDown,
  ChevronUp,
  Bookmark,
  BookmarkCheck,
  Rss,
} from 'lucide-react'
import type { EhGallery, SavedSearch } from '@/lib/types'

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
      <div className="shrink-0 w-[90px] h-[120px] bg-vault-input rounded overflow-hidden">
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
          <div className="shrink-0">
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
                {gallery.pages} {t('browse.pages')}
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
                {t('browse.download')}
              </button>
              <button
                onClick={onClose}
                className="px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors"
              >
                {t('browse.close')}
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
  { tl: 15, label: 'browse.yesterday' },
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

const CRON_PRESETS = [
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 2 hours', value: '0 */2 * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily', value: '0 0 * * *' },
]

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
  const rawTab = searchParams.get('tab')
  const initialTab: BrowseTab =
    rawTab === 'search' || rawTab === 'favorites' || rawTab === 'toplist' ? rawTab : 'popular'
  const initialFavCat = searchParams.get('favcat') || 'all'
  const initialFavSearch = searchParams.get('favsearch') || ''

  // Restore saved browse state from back-navigation (consumed once on mount)
  const [restored] = useState(() => {
    if (typeof window === 'undefined') return null
    const raw = sessionStorage.getItem('eh_browse_state')
    if (!raw) return null
    sessionStorage.removeItem('eh_browse_state')
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  })

  const [activeTab, setActiveTab] = useState<BrowseTab>(restored?.activeTab ?? initialTab)
  const [inputValue, setInputValue] = useState(initialQ)
  const [searchQuery, setSearchQuery] = useState(initialQ)
  const [category, setCategory] = useState<string | null>(null)

  // Cursor-based pagination for search tab
  const [currentCursor, setCurrentCursor] = useState<number | null>(restored?.currentCursor ?? null)
  const [prevCursors, setPrevCursors] = useState<number[]>(restored?.prevCursors ?? [])
  const [pageIndex, setPageIndex] = useState(restored?.pageIndex ?? 0)

  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [selectedGallery, setSelectedGallery] = useState<EhGallery | null>(null)
  const [colCount, setColCount] = useState(3)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Advanced search state
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [selectedCats, setSelectedCats] = useState<Set<string>>(() => {
    const catParam = searchParams.get('cat')
    if (!catParam) return new Set(Object.keys(CATEGORY_META))
    const keys = catParam.split(',').filter((k) => k in CATEGORY_META)
    return keys.length > 0 ? new Set(keys) : new Set(Object.keys(CATEGORY_META))
  })
  const [advSearch, setAdvSearch] = useState(() => {
    const adv = searchParams.get('adv')
    return adv ? Number(adv) : 0
  })
  const [minRating, setMinRating] = useState<number | null>(() => {
    const mr = searchParams.get('minrating')
    return mr ? Number(mr) : null
  })
  const [pageFrom, setPageFrom] = useState<string>(searchParams.get('pfrom') ?? '')
  const [pageTo, setPageTo] = useState<string>(searchParams.get('pto') ?? '')

  // Favorites state (cursor-based pagination — EH favorites uses next/prev cursors, not page numbers)
  const [favCat, setFavCat] = useState<string>(restored?.favCat ?? initialFavCat)
  const [favCursor, setFavCursor] = useState<{ next?: string; prev?: string }>(
    restored?.favCursor ?? {},
  )
  const [favSearch, setFavSearch] = useState(restored?.favSearch ?? initialFavSearch)
  const [favPageIndex, setFavPageIndex] = useState(restored?.favPageIndex ?? 0)

  // Infinite scroll state
  const [loadMode] = useState<LoadMode>(getLoadMode)
  const [scrollGalleries, setScrollGalleries] = useState<EhGallery[]>(
    restored?.scrollGalleries ?? [],
  )
  const [scrollPage, setScrollPage] = useState(0)
  const [scrollNextGid, setScrollNextGid] = useState<number | null>(restored?.scrollNextGid ?? null)
  const scrollNeedsSeedRef = useRef(
    restored?.scrollGalleries != null && restored.scrollGalleries.length > 0 ? false : true,
  )
  const [scrollLoading, setScrollLoading] = useState(false)
  const [scrollHasMore, setScrollHasMore] = useState(restored?.scrollHasMore ?? true)
  // Same for favorites scroll (cursor-based)
  const [favScrollGalleries, setFavScrollGalleries] = useState<EhGallery[]>(
    restored?.favScrollGalleries ?? [],
  )
  const [favScrollNextCursor, setFavScrollNextCursor] = useState<string | undefined>(
    restored?.favScrollNextCursor,
  )
  const [favScrollLoading, setFavScrollLoading] = useState(false)
  const [favScrollHasMore, setFavScrollHasMore] = useState(restored?.favScrollHasMore ?? true)

  // Toplist state — initialised from URL (or restored state) so back-navigation preserves the selection
  const [toplistTl, setToplistTl] = useState(() => {
    if (restored?.toplistTl != null) return restored.toplistTl
    const tl = searchParams.get('tl')
    return tl ? Number(tl) : 11
  })
  const [toplistPage, setToplistPage] = useState(() => {
    if (restored?.toplistPage != null) return restored.toplistPage
    const p = searchParams.get('tlpage')
    return p ? Number(p) : 0
  })

  // Subscribe to search state
  const [showSubscribe, setShowSubscribe] = useState(false)
  const [subName, setSubName] = useState('')
  const [subAutoDownload, setSubAutoDownload] = useState(true)
  const [subCron, setSubCron] = useState('0 */2 * * *')
  const { trigger: createSub, isMutating: subCreating } = useCreateSubscription()

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
  const mobileSavedSearchesRef = useRef<HTMLDivElement>(null)

  // EH credentials (for favorites tab)
  const { data: credData, isLoading: credLoading } = useSWR('settings/credentials/eh', () =>
    api.settings.getCredentials(),
  )
  const ehConfigured = credLoading ? true : !!credData?.ehentai?.configured

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
      const target = e.target as Node
      const inDesktop = savedSearchesRef.current?.contains(target)
      const inMobile = mobileSavedSearchesRef.current?.contains(target)
      if (!inDesktop && !inMobile) {
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
  // Only react to the q param itself, not to other searchParams changes (tab, etc.)
  // to avoid a feedback loop where the URL sync effect resets cursors.
  const urlQ = searchParams.get('q') || ''
  useEffect(() => {
    if (urlQ !== searchQuery) {
      setInputValue(urlQ)
      setSearchQuery(urlQ)
      setCurrentCursor(null)
      setPrevCursors([])
      setPageIndex(0)
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
    if (activeTab !== 'search') params.set('tab', activeTab)
    if (activeTab === 'favorites' && favCat !== 'all') params.set('favcat', favCat)
    if (activeTab === 'favorites' && favSearch) params.set('favsearch', favSearch)
    if (activeTab === 'toplist' && toplistTl !== 11) params.set('tl', String(toplistTl))
    if (activeTab === 'toplist' && toplistPage > 0) params.set('tlpage', String(toplistPage))
    if (selectedCats.size < Object.keys(CATEGORY_META).length) {
      params.set('cat', [...selectedCats].sort().join(','))
    }
    if (minRating !== null && minRating !== undefined) params.set('minrating', String(minRating))
    if (advSearch !== 0) params.set('adv', String(advSearch))
    if (pageFrom) params.set('pfrom', pageFrom)
    if (pageTo) params.set('pto', pageTo)
    const qs = params.toString()
    router.replace(qs ? `/e-hentai?${qs}` : '/e-hentai', { scroll: false })
  }, [
    searchQuery,
    activeTab,
    favCat,
    favSearch,
    toplistTl,
    toplistPage,
    selectedCats,
    minRating,
    advSearch,
    pageFrom,
    pageTo,
  ]) // eslint-disable-line react-hooks/exhaustive-deps

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

  // SWR only handles the current view (first page in scroll mode, cursor page in pagination mode).
  // Scroll mode fetches subsequent pages imperatively via onLoadMore.
  const { data, isLoading, error } = useEhSearch(
    {
      q: searchQuery || undefined,
      ...(loadMode === 'pagination' && currentCursor != null ? { next_gid: currentCursor } : {}),
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
    },
    activeTab === 'search' || !!searchQuery,
  )

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
  } = useEhPopular(activeTab === 'popular')

  const {
    data: toplistData,
    isLoading: toplistLoading,
    error: toplistError,
  } = useEhToplist(toplistTl, toplistPage, activeTab === 'toplist')

  // Restore scroll position after back-navigation (once data is loaded)
  const scrollRestoredRef = useRef(false)
  useEffect(() => {
    if (scrollRestoredRef.current || !restored?.scrollY) return
    const hasData =
      activeTab === 'search' || activeTab === 'popular'
        ? !!data || scrollGalleries.length > 0
        : activeTab === 'favorites'
          ? !!favData || favScrollGalleries.length > 0
          : !!toplistData
    if (!hasData) return
    scrollRestoredRef.current = true
    requestAnimationFrame(() => {
      window.scrollTo(0, restored.scrollY)
    })
  }, [data, favData, toplistData, scrollGalleries.length, favScrollGalleries.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Infinite scroll: reset when search changes ─────────
  useEffect(() => {
    if (loadMode === 'scroll') {
      setScrollGalleries([])
      setScrollPage(0)
      setScrollNextGid(null)
      setScrollHasMore(true)
      scrollNeedsSeedRef.current = true // Mark for re-seeding
    }
  }, [searchQuery, category, loadMode, advSearch, minRating, pageFrom, pageTo, selectedCats.size])

  // Initialize scroll mode with first page from SWR
  useEffect(() => {
    if (loadMode !== 'scroll' || !data || activeTab !== 'search') return
    if (scrollNeedsSeedRef.current) {
      setScrollGalleries(data.galleries)
      setScrollNextGid(data.next_gid ?? null)
      setScrollHasMore(data.next_gid != null)
      setScrollPage(0)
      scrollNeedsSeedRef.current = false
    }
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

  // ── Handlers ────────────────────────────────────────────

  const commitSearch = useCallback((q: string) => {
    addSearchHistory(q)
    setSearchQuery(q)
    setCurrentCursor(null)
    setPrevCursors([])
    setPageIndex(0)
    setScrollGalleries([])
    setScrollPage(0)
    setScrollNextGid(null)
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
      setCurrentCursor(null)
      setPrevCursors([])
      setPageIndex(0)
    },
    [showAdvanced],
  )

  // Save all pagination state to sessionStorage before navigating to a gallery detail page
  const saveBrowseState = useCallback(() => {
    sessionStorage.setItem(
      'eh_browse_state',
      JSON.stringify({
        activeTab,
        scrollY: window.scrollY,
        // Search pagination
        pageIndex,
        currentCursor,
        prevCursors,
        // Favorites
        favCat,
        favCursor,
        favSearch,
        favPageIndex,
        // Toplist
        toplistTl,
        toplistPage,
        // Scroll mode accumulated data (only save when relevant)
        ...(loadMode === 'scroll' && activeTab === 'search'
          ? { scrollGalleries, scrollNextGid, scrollHasMore }
          : {}),
        ...(loadMode === 'scroll' && activeTab === 'favorites'
          ? { favScrollGalleries, favScrollNextCursor, favScrollHasMore }
          : {}),
      }),
    )
  }, [
    activeTab,
    pageIndex,
    currentCursor,
    prevCursors,
    favCat,
    favCursor,
    favSearch,
    favPageIndex,
    toplistTl,
    toplistPage,
    loadMode,
    scrollGalleries,
    scrollNextGid,
    scrollHasMore,
    favScrollGalleries,
    favScrollNextCursor,
    favScrollHasMore,
  ])

  const navigateToGallery = useCallback(
    (g: EhGallery) => {
      saveBrowseState()
      const fav = activeTab === 'favorites' ? '?fav=1' : ''
      router.push(`/e-hentai/${g.gid}/${g.token}${fav}`)
    },
    [router, activeTab, saveBrowseState],
  )

  const handleDownload = useCallback(async (g: EhGallery) => {
    const url = `https://e-hentai.org/g/${g.gid}/${g.token}/`
    try {
      const res = await api.download.enqueue(url)
      toast.success(t('browse.addedToQueueJob', { jobId: res.job_id }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }, [])

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

  const handleSubscribe = async () => {
    const subUrl = `https://e-hentai.org/?f_search=${encodeURIComponent(searchQuery)}`
    try {
      await createSub({
        url: subUrl,
        name: subName.trim() || searchQuery,
        auto_download: subAutoDownload,
        cron_expr: subCron,
      })
      toast.success(t('browse.subscribeSuccess'))
      setShowSubscribe(false)
      setSubName('')
    } catch {
      toast.error(t('browse.subscribeFailed'))
    }
  }

  const clearSearch = useCallback(() => {
    setInputValue('')
    setSearchQuery('')
    setCurrentCursor(null)
    setPrevCursors([])
    setPageIndex(0)
    setScrollGalleries([])
    setScrollPage(0)
    setScrollNextGid(null)
    setScrollHasMore(true)
    scrollNeedsSeedRef.current = true
  }, [])

  const displayGalleries = useMemo(
    () => (loadMode === 'scroll' ? scrollGalleries : (data?.galleries ?? [])),
    [loadMode, scrollGalleries, data?.galleries],
  )
  const favDisplayGalleries = useMemo(
    () => (loadMode === 'scroll' ? favScrollGalleries : (favData?.galleries ?? [])),
    [loadMode, favScrollGalleries, favData?.galleries],
  )

  // ── Keyboard grid navigation ────────────────────────────
  // Active for search/latest and popular tabs (grid mode only)
  const activeGalleries =
    activeTab === 'popular' && !searchQuery ? (popularData?.galleries ?? []) : displayGalleries

  const { focusedIndex } = useGridKeyboard({
    totalItems: activeGalleries.length,
    colCount,
    onEnter: (i) => {
      const g = activeGalleries[i]
      if (g) {
        saveBrowseState()
        router.push(`/e-hentai/${g.gid}/${g.token}`)
      }
    },
    enabled:
      viewMode === 'grid' && (activeTab === 'search' || activeTab === 'popular' || !!searchQuery),
  })

  // ── Render ─────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Credential banner (shown when EH credentials are not configured) */}
      {!ehConfigured && <CredentialBanner source="ehentai" />}

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

        {/* Mobile saved searches button */}
        <div ref={mobileSavedSearchesRef} className="relative sm:hidden shrink-0">
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

          {/* Mobile saved searches dropdown */}
          {showSavedSearches && (
            <div className="absolute left-0 top-full mt-1 z-40 w-72 max-w-[calc(100vw-2rem)] bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden">
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

        {/* Subscribe to search button (desktop) */}
        {searchQuery && (
          <div className="relative hidden sm:block shrink-0">
            <button
              onClick={() => setShowSubscribe(!showSubscribe)}
              title={t('browse.subscribeToSearch')}
              className="p-2.5 bg-vault-card border border-vault-border rounded-lg text-vault-text-secondary hover:text-vault-accent transition-colors"
            >
              <Rss size={18} />
            </button>
            {showSubscribe && (
              <div className="absolute right-0 top-full mt-1 z-40 w-80 bg-vault-card border border-vault-border rounded-lg shadow-xl p-4 space-y-3">
                <h3 className="text-sm font-medium text-vault-text">
                  {t('browse.subscribeToSearch')}
                </h3>
                <div>
                  <label className="text-xs text-vault-text-muted block mb-1">URL</label>
                  <input
                    type="text"
                    readOnly
                    value={`https://e-hentai.org/?f_search=${encodeURIComponent(searchQuery)}`}
                    className="w-full px-2 py-1.5 bg-vault-input border border-vault-border rounded text-xs text-vault-text-muted"
                  />
                </div>
                <div>
                  <label className="text-xs text-vault-text-muted block mb-1">
                    {t('subscriptions.name')}
                  </label>
                  <input
                    type="text"
                    value={subName}
                    onChange={(e) => setSubName(e.target.value)}
                    placeholder={searchQuery}
                    className="w-full px-2 py-1.5 bg-vault-input border border-vault-border rounded text-sm text-vault-text placeholder-vault-text-muted"
                  />
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-vault-text-muted">
                      {t('subscriptions.autoDownload')}
                    </label>
                    <button
                      onClick={() => setSubAutoDownload(!subAutoDownload)}
                      className={`relative w-9 h-5 rounded-full transition-colors ${subAutoDownload ? 'bg-vault-accent' : 'bg-vault-border'}`}
                    >
                      <span
                        className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${subAutoDownload ? 'translate-x-4' : ''}`}
                      />
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-vault-text-muted">
                      {t('subscriptions.cronExpr')}
                    </label>
                    <select
                      value={subCron}
                      onChange={(e) => setSubCron(e.target.value)}
                      className="px-2 py-1 bg-vault-input border border-vault-border rounded text-xs text-vault-text"
                    >
                      {CRON_PRESETS.map((p) => (
                        <option key={p.value} value={p.value}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <button
                  onClick={handleSubscribe}
                  disabled={subCreating}
                  className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors disabled:opacity-50"
                >
                  {subCreating ? t('subscriptions.adding') : t('subscriptions.add')}
                </button>
              </div>
            )}
          </div>
        )}

        {/* View toggle */}
        <div className="flex border border-vault-border rounded-lg overflow-hidden shrink-0">
          <button
            onClick={() => setViewMode('list')}
            title={t('browse.listView')}
            className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'list' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            ☰
          </button>
          <button
            onClick={() => setViewMode('grid')}
            title={t('browse.gridView')}
            className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'grid' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            ⊞
          </button>
        </div>
      </div>

      {/* ── Search mode: clear header (replaces tabs) ── */}
      {searchQuery && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-vault-text-secondary">
            {t('browse.resultsFor', { query: searchQuery })}
          </span>
          <button
            onClick={clearSearch}
            className="text-xs text-vault-text-muted hover:text-vault-text transition-colors"
          >
            {t('browse.clearSearch')}
          </button>
        </div>
      )}

      {/* ── Tab switcher (hidden when searching) ── */}
      {!searchQuery && (
        <div className="flex gap-1 border-b border-vault-border overflow-x-auto scrollbar-hide">
          <button
            onClick={() => setActiveTab('popular')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'popular'
                ? 'border-orange-400 text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.popularTab')}
          </button>
          <button
            onClick={() => {
              setActiveTab('search')
              setCurrentCursor(null)
              setPrevCursors([])
              setPageIndex(0)
            }}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'search'
                ? 'border-vault-accent text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.latestTab')}
          </button>
          <button
            onClick={() => {
              setActiveTab('toplist')
              setToplistPage(0)
            }}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'toplist'
                ? 'border-yellow-400 text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.toplistTab')}
          </button>
          {ehConfigured && (
            <button
              onClick={() => {
                setActiveTab('favorites')
                setFavCursor({})
                setFavPageIndex(0)
              }}
              className={`shrink-0 ml-3 md:ml-auto px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'favorites'
                  ? 'border-[#e91e63] text-vault-text'
                  : 'border-transparent text-vault-text-muted hover:text-vault-text'
              }`}
            >
              {t('browse.favoritesTab')}
            </button>
          )}
        </div>
      )}

      {/* ════════ SEARCH/LATEST CONTENT ════════ */}
      {/* Show when: searching (any tab) OR on Latest tab (no search query) */}
      {(searchQuery || activeTab === 'search') && (
        <>
          {/* ── Category filter row ── */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
            <button
              onClick={() => handleCategoryClick(null)}
              className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
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
                  className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-all ${
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
              {t('browse.advancedSearch')}
              {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>

            {showAdvanced && (
              <div className="mt-2 bg-vault-card border border-vault-border rounded-lg p-4 space-y-4">
                {/* Search in */}
                <div>
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    {t('browse.searchIn')}
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
                    {t('browse.filters')}
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
                    <p className="text-xs text-vault-text-muted mb-1">{t('browse.minRating')}</p>
                    <select
                      value={minRating ?? ''}
                      onChange={(e) => setMinRating(e.target.value ? Number(e.target.value) : null)}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                    >
                      <option value="">{t('browse.anyRating')}</option>
                      <option value="2">2+</option>
                      <option value="3">3+</option>
                      <option value="4">4+</option>
                      <option value="5">5</option>
                    </select>
                  </div>
                  <div>
                    <p className="text-xs text-vault-text-muted mb-1">{t('browse.pageRange')}</p>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        value={pageFrom}
                        onChange={(e) => setPageFrom(e.target.value)}
                        placeholder={t('browse.pageFrom')}
                        className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                      />
                      <span className="text-vault-text-muted text-xs">-</span>
                      <input
                        type="number"
                        value={pageTo}
                        onChange={(e) => setPageTo(e.target.value)}
                        placeholder={t('browse.pageTo')}
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
                  {t('browse.resetAdvanced')}
                </button>
              </div>
            )}
          </div>

          {/* ── Results header ── */}
          {data && !isLoading && (
            <div className="flex items-center justify-between text-xs text-vault-text-muted">
              <span>
                {searchQuery
                  ? t('browse.resultsFor', { query: searchQuery })
                  : t('browse.resultsCount', { count: data.total.toLocaleString() })}
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
                <span>{t('browse.pageN', { page: String(pageIndex + 1) })}</span>
              </div>
            </div>
          )}

          {/* ── Loading (only when no data yet) ── */}
          {isLoading && displayGalleries.length === 0 && (
            <div className="flex justify-center py-4">
              <LoadingSpinner />
            </div>
          )}

          {/* ── Error ── */}
          {error && !isLoading && (
            <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
              {error.message?.includes('credentials not configured') ||
              error.message?.includes('503') ? (
                <p className="text-yellow-400">{t('browse.credentialsMissingDetail')}</p>
              ) : (
                <p className="text-red-400">{error.message || t('browse.failedLoadResults')}</p>
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
                <VirtualGrid
                  items={displayGalleries}
                  columns={{ base: 3, sm: 4, md: 5, lg: 6, xl: 7, xxl: 8 }}
                  gap={8}
                  estimateHeight={220}
                  focusedIndex={focusedIndex}
                  onColCountChange={setColCount}
                  renderItem={(g) => (
                    <GridCard
                      key={`${g.gid}-${g.token}`}
                      gallery={g}
                      onClick={() => navigateToGallery(g)}
                    />
                  )}
                  onLoadMore={
                    loadMode === 'scroll'
                      ? () => {
                          if (!scrollHasMore || scrollLoading || !scrollNextGid) return
                          setScrollLoading(true)
                          const cursor = scrollNextGid
                          api.eh
                            .search({
                              q: searchQuery || undefined,
                              next_gid: cursor,
                              ...(showAdvanced
                                ? {
                                    f_cats: computedFCats,
                                    advance:
                                      advSearch !== 0 ||
                                      minRating !== null ||
                                      pageFrom !== '' ||
                                      pageTo !== '',
                                    adv_search: advSearch || undefined,
                                    min_rating: minRating || undefined,
                                    page_from: pageFrom ? Number(pageFrom) : undefined,
                                    page_to: pageTo ? Number(pageTo) : undefined,
                                  }
                                : { category: category || undefined }),
                            })
                            .then((result) => {
                              setScrollGalleries((prev) => {
                                const existingIds = new Set(prev.map((g) => g.gid))
                                const newOnes = result.galleries.filter(
                                  (g) => !existingIds.has(g.gid),
                                )
                                return [...prev, ...newOnes]
                              })
                              setScrollNextGid(result.next_gid ?? null)
                              setScrollHasMore(result.next_gid != null)
                              setScrollPage((p) => p + 1)
                              setScrollLoading(false)
                            })
                            .catch(() => {
                              setScrollLoading(false)
                            })
                        }
                      : undefined
                  }
                  hasMore={loadMode === 'scroll' ? scrollHasMore : false}
                  isLoading={loadMode === 'scroll' ? scrollLoading || isLoading : false}
                />
              )}

              {/* Pagination mode — cursor-based prev/next */}
              {loadMode === 'pagination' && data && (data.has_prev || data.next_gid) && (
                <Paginator
                  page={pageIndex}
                  hasPrev={pageIndex > 0}
                  hasNext={!!data.next_gid}
                  onFirst={() => {
                    setCurrentCursor(null)
                    setPrevCursors([])
                    setPageIndex(0)
                    window.scrollTo(0, 0)
                  }}
                  onPrev={() => {
                    if (pageIndex === 0) return
                    const stack = [...prevCursors]
                    const prev = stack.pop()
                    setPrevCursors(stack)
                    setCurrentCursor(prev === 0 ? null : (prev ?? null))
                    setPageIndex((p: number) => p - 1)
                    window.scrollTo(0, 0)
                  }}
                  onNext={() => {
                    if (!data?.next_gid) return
                    setPrevCursors((prev) => [...prev, currentCursor ?? 0])
                    setCurrentCursor(data.next_gid)
                    setPageIndex((p: number) => p + 1)
                    window.scrollTo(0, 0)
                  }}
                  onJump={(target) => {
                    if (target === pageIndex) return
                    if (target === 0) {
                      setCurrentCursor(null)
                      setPrevCursors([])
                      setPageIndex(0)
                      window.scrollTo(0, 0)
                    } else if (target < pageIndex) {
                      const stepsBack = pageIndex - target
                      const stack = [...prevCursors]
                      for (let i = 0; i < stepsBack - 1; i++) stack.pop()
                      const cursor = stack.pop() ?? null
                      setPrevCursors(stack)
                      setCurrentCursor(cursor === 0 ? null : cursor)
                      setPageIndex(target)
                      window.scrollTo(0, 0)
                    } else {
                      // Jump forward — sequentially fetch cursors
                      const stepsForward = target - pageIndex
                      const jumpSearchParams = {
                        q: searchQuery || undefined,
                        ...(showAdvanced
                          ? {
                              f_cats: computedFCats,
                              advance:
                                advSearch !== 0 ||
                                minRating !== null ||
                                pageFrom !== '' ||
                                pageTo !== '',
                              adv_search: advSearch || undefined,
                              min_rating: minRating || undefined,
                              page_from: pageFrom ? Number(pageFrom) : undefined,
                              page_to: pageTo ? Number(pageTo) : undefined,
                            }
                          : { category: category || undefined }),
                      }
                      let cursor = data?.next_gid
                      if (!cursor) {
                        toast.error(t('browse.cannotJumpForward'))
                        return
                      }
                      const newCursors = [...prevCursors, currentCursor ?? 0]
                      ;(async () => {
                        try {
                          for (let i = 0; i < stepsForward - 1; i++) {
                            const result = await api.eh.search({
                              ...jumpSearchParams,
                              next_gid: cursor,
                            })
                            if (!result.next_gid) {
                              newCursors.push(cursor!)
                              setPrevCursors(newCursors)
                              setCurrentCursor(cursor!)
                              setPageIndex(pageIndex + i + 1)
                              window.scrollTo(0, 0)
                              toast.error(t('browse.cannotJumpForward'))
                              return
                            }
                            newCursors.push(cursor!)
                            cursor = result.next_gid
                          }
                          setPrevCursors(newCursors)
                          setCurrentCursor(cursor!)
                          setPageIndex(target)
                          window.scrollTo(0, 0)
                        } catch {
                          toast.error(t('browse.cannotJumpForward'))
                        }
                      })()
                    }
                  }}
                />
              )}

              {/* Scroll mode end indicator */}
              {loadMode === 'scroll' && !scrollHasMore && (
                <div className="flex justify-center py-4">
                  <span className="text-xs text-vault-text-muted">{t('browse.noMoreResults')}</span>
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
      {!searchQuery && activeTab === 'favorites' && ehConfigured && (
        <>
          {/* ── Favorites category pills (All + 0-9) ── */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
            <button
              onClick={() => {
                setFavCat('all')
                setFavCursor({})
                setFavPageIndex(0)
                setFavScrollGalleries([])
                setFavScrollNextCursor(undefined)
                setFavScrollHasMore(true)
              }}
              className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
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
                    setFavPageIndex(0)
                    setFavScrollGalleries([])
                    setFavScrollNextCursor(undefined)
                    setFavScrollHasMore(true)
                  }}
                  className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
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
              setFavPageIndex(0)
            }}
            placeholder={t('browse.filterFavorites')}
            className="w-full bg-vault-card border border-vault-border rounded-lg px-4 py-2 text-sm
                     text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors"
          />

          {/* Favorites results header */}
          {favData && !favLoading && (
            <div className="flex items-center justify-between text-xs text-vault-text-muted">
              <span>
                {favData.total.toLocaleString()} {t('browse.favorited')}
                {favSearch && ` ${t('browse.matchingQuery', { query: favSearch })}`}
              </span>
            </div>
          )}

          {/* Favorites loading (only when no data yet) */}
          {favLoading && favDisplayGalleries.length === 0 && (
            <div className="flex justify-center py-4">
              <LoadingSpinner />
            </div>
          )}

          {/* Favorites error */}
          {favError && !favLoading && (
            <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
              <p className="text-red-400">{favError.message || t('browse.failedLoadFavorites')}</p>
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
                <VirtualGrid
                  items={favDisplayGalleries}
                  columns={{ base: 3, sm: 4, md: 5, lg: 6, xl: 7, xxl: 8 }}
                  gap={8}
                  estimateHeight={220}
                  renderItem={(g) => (
                    <GridCard
                      key={`${g.gid}-${g.token}`}
                      gallery={g}
                      onClick={() => navigateToGallery(g)}
                    />
                  )}
                  onLoadMore={
                    loadMode === 'scroll'
                      ? () => {
                          if (
                            favScrollHasMore &&
                            !favScrollLoading &&
                            !favLoading &&
                            favScrollNextCursor
                          ) {
                            setFavScrollLoading(true)
                            setFavCursor({ next: favScrollNextCursor })
                          }
                        }
                      : undefined
                  }
                  hasMore={loadMode === 'scroll' ? favScrollHasMore : false}
                  isLoading={loadMode === 'scroll' ? favScrollLoading || favLoading : false}
                />
              )}

              {/* Pagination mode — cursor-based prev/next */}
              {loadMode === 'pagination' && (favData?.has_prev || favData?.has_next) && (
                <Paginator
                  page={favPageIndex}
                  hasPrev={!!favData?.has_prev}
                  hasNext={!!favData?.has_next}
                  onFirst={() => {
                    setFavCursor({})
                    setFavPageIndex(0)
                    window.scrollTo(0, 0)
                  }}
                  onPrev={() => {
                    if (favData?.prev_cursor) {
                      setFavCursor({ prev: favData.prev_cursor })
                      setFavPageIndex((p: number) => Math.max(0, p - 1))
                      window.scrollTo(0, 0)
                    }
                  }}
                  onNext={() => {
                    if (favData?.next_cursor) {
                      setFavCursor({ next: favData.next_cursor })
                      setFavPageIndex((p: number) => p + 1)
                      window.scrollTo(0, 0)
                    }
                  }}
                />
              )}

              {/* Scroll mode end indicator */}
              {loadMode === 'scroll' && !favScrollHasMore && (
                <div className="flex justify-center py-4">
                  <span className="text-xs text-vault-text-muted">
                    {t('browse.noMoreFavorites')}
                  </span>
                </div>
              )}
            </>
          )}

          {/* Favorites empty */}
          {!favLoading && !favError && favData && favDisplayGalleries.length === 0 && (
            <div className="text-center py-20 text-vault-text-muted">{t('browse.noFavorites')}</div>
          )}
        </>
      )}

      {/* ════════ POPULAR TAB ════════ */}
      {!searchQuery && activeTab === 'popular' && (
        <>
          {popularLoading && !popularData && (
            <div className="flex justify-center py-4">
              <LoadingSpinner />
            </div>
          )}

          {popularError && !popularLoading && (
            <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
              <p className="text-red-400">
                {popularError.message || t('browse.failedLoadPopular')}
              </p>
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
                <VirtualGrid
                  items={popularData.galleries}
                  columns={{ base: 3, sm: 4, md: 5, lg: 6, xl: 7, xxl: 8 }}
                  gap={8}
                  estimateHeight={220}
                  focusedIndex={focusedIndex}
                  onColCountChange={setColCount}
                  renderItem={(g) => (
                    <GridCard
                      key={`${g.gid}-${g.token}`}
                      gallery={g}
                      onClick={() => navigateToGallery(g)}
                    />
                  )}
                />
              )}
            </>
          )}

          {!popularLoading && !popularError && popularData?.galleries.length === 0 && (
            <div className="text-center py-20 text-vault-text-muted">{t('common.noResults')}</div>
          )}
        </>
      )}

      {/* ════════ TOPLIST TAB ════════ */}
      {!searchQuery && activeTab === 'toplist' && (
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
                className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  toplistTl === tl
                    ? 'bg-yellow-500 text-black border-yellow-500'
                    : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
                }`}
              >
                {t(label)}
              </button>
            ))}
          </div>

          {toplistLoading && !toplistData && (
            <div className="flex justify-center py-4">
              <LoadingSpinner />
            </div>
          )}

          {toplistError && !toplistLoading && (
            <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
              <p className="text-red-400">
                {toplistError.message || t('browse.failedLoadTopLists')}
              </p>
            </div>
          )}

          {toplistData && !toplistLoading && (
            <>
              <div className="flex items-center justify-between text-xs text-vault-text-muted">
                <span>
                  {toplistData.total.toLocaleString()} {t('browse.results')}
                </span>
                <span>{t('browse.pageN', { page: String(toplistPage + 1) })}</span>
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
                <VirtualGrid
                  items={toplistData.galleries}
                  columns={{ base: 3, sm: 4, md: 5, lg: 6, xl: 7, xxl: 8 }}
                  gap={8}
                  estimateHeight={220}
                  renderItem={(g) => (
                    <GridCard
                      key={`${g.gid}-${g.token}`}
                      gallery={g}
                      onClick={() => navigateToGallery(g)}
                    />
                  )}
                />
              )}

              {/* Toplist pagination */}
              {toplistData.galleries.length > 0 && (
                <Paginator
                  page={toplistPage}
                  hasPrev={toplistPage > 0}
                  hasNext={toplistData.galleries.length >= EH_PAGE_SIZE}
                  onFirst={() => {
                    setToplistPage(0)
                    window.scrollTo(0, 0)
                  }}
                  onPrev={() => {
                    setToplistPage((p: number) => Math.max(0, p - 1))
                    window.scrollTo(0, 0)
                  }}
                  onNext={() => {
                    setToplistPage((p: number) => p + 1)
                    window.scrollTo(0, 0)
                  }}
                  onJump={(target) => {
                    setToplistPage(Math.max(0, target))
                    window.scrollTo(0, 0)
                  }}
                />
              )}
            </>
          )}

          {!toplistLoading && !toplistError && toplistData?.galleries.length === 0 && (
            <div className="text-center py-20 text-vault-text-muted">{t('common.noResults')}</div>
          )}
        </>
      )}

      {/* Gallery detail modal */}
      {selectedGallery && (
        <GalleryModal
          gallery={selectedGallery}
          onClose={() => setSelectedGallery(null)}
          onDownload={(g) => {
            setSelectedGallery(null)
            handleDownload(g)
          }}
        />
      )}
    </div>
  )
}
