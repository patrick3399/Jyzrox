'use client'

import { useState, useRef, useCallback, useEffect, useMemo, Suspense } from 'react'
import { useRouter } from 'next/navigation'
import { useEhBrowse } from '@/hooks/useEhBrowse'
import {
  EH_ADVANCED_SEARCH_BITS,
  parseEhSavedSearch,
  queryKey,
  serializeEhSavedSearchParams,
} from '@/lib/ehBrowseState'
import { getEhGalleryLanguage } from '@/lib/ehGalleryLanguage'
import {
  applyEhAutocompleteSuggestion,
  getEhAutocompleteFragment,
} from '@/lib/ehSearchAutocomplete'
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
import {
  Search as SearchIcon,
  X as XIcon,
  ChevronDown,
  ChevronUp,
  Bookmark,
  BookmarkCheck,
  Rss,
} from 'lucide-react'
import type { EhBrowseGalleryStatus, EhGallery, SavedSearch, TagItem } from '@/lib/types'

// ── IntersectionObserver-based lazy image ──────────────────────────────

function LazyImage({ src, alt, className }: { src: string; alt: string; className: string }) {
  const [error, setError] = useState(false)

  if (error) {
    return <div className={`${className} bg-vault-input`} />
  }

  return <img src={src} alt={alt} className={className} onError={() => setError(true)} />
}

function SearchAutocompleteDropdown({
  suggestions,
  highlightedIndex,
  onSelect,
  onHighlight,
}: {
  suggestions: TagItem[]
  highlightedIndex: number
  onSelect: (tag: TagItem) => void
  onHighlight: (index: number) => void
}) {
  if (suggestions.length === 0) return null
  return (
    <ul className="absolute left-0 right-0 top-full mt-1 z-40 bg-vault-card border border-vault-border rounded-lg shadow-xl overflow-hidden max-h-[min(360px,55vh)] overflow-y-auto">
      {suggestions.map((tag, index) => (
        <li key={`${tag.namespace}:${tag.name}`}>
          <button
            type="button"
            onMouseDown={(event) => {
              event.preventDefault()
              onSelect(tag)
            }}
            onMouseEnter={() => onHighlight(index)}
            className={`w-full flex items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors ${
              highlightedIndex === index
                ? 'bg-vault-accent/10 text-vault-accent'
                : 'text-vault-text hover:bg-vault-card-hover'
            }`}
          >
            <span className="min-w-0 truncate">
              <span className="text-vault-text-muted text-xs">{tag.namespace}:</span>
              <span className="font-medium">{tag.name}</span>
              {tag.translation && (
                <span className="text-vault-text-muted text-xs ml-1">({tag.translation})</span>
              )}
            </span>
            <span className="text-xs text-vault-text-muted shrink-0">{tag.count}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

// ── Search history (localStorage) ─────────────────────────────────────

const HISTORY_KEY = 'eh_search_history'
const HISTORY_ENABLED_KEY = 'eh_search_history_enabled'
const VIEW_MODE_KEY = 'eh_view_mode'
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

function ListCard({
  gallery,
  status,
  onClick,
}: {
  gallery: EhGallery
  status?: EhBrowseGalleryStatus
  onClick: () => void
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

function GridCard({
  gallery,
  status,
  onClick,
}: {
  gallery: EhGallery
  status?: EhBrowseGalleryStatus
  onClick: () => void
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

// ── Main page ──────────────────────────────────────────────────────────

type ViewMode = 'list' | 'grid'

// Toplist time-period IDs (EH convention)
const TOPLIST_OPTIONS: { tl: number; label: string }[] = [
  { tl: 11, label: 'browse.allTime' },
  { tl: 12, label: 'browse.pastYear' },
  { tl: 13, label: 'browse.pastMonth' },
  { tl: 15, label: 'browse.yesterday' },
]

const CATEGORIES = Object.entries(CATEGORY_META).map(([value, { color, label }]) => ({
  value,
  label,
  color,
}))

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

const CRON_PRESETS = [
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 2 hours', value: '0 */2 * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily', value: '0 0 * * *' },
]

function getInitialViewMode(): ViewMode {
  if (typeof window === 'undefined') return 'grid'
  return (localStorage.getItem(VIEW_MODE_KEY) as ViewMode) || 'grid'
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
  const { state, actions, loadMore, favCategories } = useEhBrowse()

  // ── Local UI state (not part of query identity) ──
  const [inputValue, setInputValue] = useState(state.query)
  const [favSearchInput, setFavSearchInput] = useState(state.filters.favSearch)
  const [viewMode, setViewMode] = useState<ViewMode>(getInitialViewMode)
  const setViewModePersist = useCallback((m: ViewMode) => {
    setViewMode(m)
    if (typeof window !== 'undefined') localStorage.setItem(VIEW_MODE_KEY, m)
  }, [])
  const [colCount, setColCount] = useState(3)
  const [showAdvanced, setShowAdvanced] = useState(state.filters.advancedOpen)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const favDebounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Keep the search box text in sync when identity changes externally (tag deep-links)
  useEffect(() => {
    setInputValue(state.query)
  }, [state.query])
  useEffect(() => {
    setFavSearchInput(state.filters.favSearch)
  }, [state.filters.favSearch])

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
  const [autocompleteHighlight, setAutocompleteHighlight] = useState(-1)
  const searchBoxRef = useRef<HTMLDivElement>(null)

  const autocompleteFragment = useMemo(() => getEhAutocompleteFragment(inputValue), [inputValue])
  const { data: autocompleteData } = useSWR<TagItem[]>(
    autocompleteFragment && inputValue.trim()
      ? ['tags/autocomplete', autocompleteFragment.query]
      : null,
    () => api.tags.autocomplete(autocompleteFragment?.query ?? '', 10),
    { keepPreviousData: false },
  )
  const autocompleteSuggestions = Array.isArray(autocompleteData) ? autocompleteData : []

  // Mobile search expand
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const mobileInputRef = useRef<HTMLInputElement>(null)
  const mobileSavedSearchesRef = useRef<HTMLDivElement>(null)

  // EH credentials (for favorites tab)
  const { data: credData, isLoading: credLoading } = useSWR('settings/credentials/eh', () =>
    api.settings.getCredentials(),
  )
  const ehConfigured = credLoading ? true : !!credData?.ehentai?.configured

  // ── Data derivations ──
  const { tab, query, filters, items, total } = state
  const browseStatusGids = useMemo(
    () => Array.from(new Set(items.map((gallery) => gallery.gid))),
    [items],
  )
  const { data: browseStatusData } = useSWR(
    browseStatusGids.length > 0 ? ['eh/browse-status', browseStatusGids.join(',')] : null,
    () => api.eh.getBrowseStatus(browseStatusGids),
    { keepPreviousData: true },
  )
  const browseStatuses = browseStatusData?.statuses ?? {}
  const isSearchView = tab === 'search' || !!query
  const seeding = state.status === 'seeding'
  const loading = state.status === 'seeding' || state.status === 'loading'

  // ── Seed whenever the query identity changes and nothing is loaded ──
  const seedKey = useMemo(() => queryKey(state), [state.tab, state.query, state.filters]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (items.length === 0 && state.hasMore && state.status === 'idle') {
      // Favorites requires credentials
      if (tab === 'favorites' && !ehConfigured) return
      loadMore()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedKey, ehConfigured])

  // ── Restore scroll position after the buffer renders ──
  // Re-armed on every identity switch so an in-page tab round-trip (snapshot
  // RESTORE without a remount) re-applies the banked scroll position too.
  const scrollApplied = useRef(false)
  useEffect(() => {
    scrollApplied.current = false
  }, [seedKey])
  useEffect(() => {
    if (scrollApplied.current || items.length === 0 || state.scrollY <= 0) return
    scrollApplied.current = true
    requestAnimationFrame(() => window.scrollTo(0, state.scrollY))
  }, [seedKey, items.length, state.scrollY])

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

  // ── Handlers ────────────────────────────────────────────

  const commitSearch = useCallback(
    (q: string) => {
      addSearchHistory(q)
      actions.commitQuery(q)
      setShowHistory(false)
    },
    [actions],
  )

  const handleInputChange = useCallback(
    (value: string) => {
      setInputValue(value)
      setAutocompleteHighlight(-1)
      if (value.trim()) setShowHistory(false)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => commitSearch(value), 600)
    },
    [commitSearch],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'ArrowDown' && autocompleteSuggestions.length > 0) {
        e.preventDefault()
        setAutocompleteHighlight((index) => Math.min(index + 1, autocompleteSuggestions.length - 1))
      } else if (e.key === 'ArrowUp' && autocompleteSuggestions.length > 0) {
        e.preventDefault()
        setAutocompleteHighlight((index) => Math.max(index - 1, -1))
      } else if (
        e.key === 'Enter' &&
        autocompleteFragment &&
        autocompleteHighlight >= 0 &&
        autocompleteSuggestions[autocompleteHighlight]
      ) {
        e.preventDefault()
        handleInputChange(
          applyEhAutocompleteSuggestion(
            inputValue,
            autocompleteFragment,
            autocompleteSuggestions[autocompleteHighlight],
          ),
        )
      } else if (e.key === 'Enter') {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        commitSearch(inputValue)
      } else if (e.key === 'Escape') {
        setShowHistory(false)
        setAutocompleteHighlight(-1)
      }
    },
    [
      inputValue,
      commitSearch,
      handleInputChange,
      autocompleteFragment,
      autocompleteHighlight,
      autocompleteSuggestions,
    ],
  )

  const handleAutocompleteSelect = useCallback(
    (tag: TagItem) => {
      if (!autocompleteFragment) return
      handleInputChange(applyEhAutocompleteSuggestion(inputValue, autocompleteFragment, tag))
    },
    [autocompleteFragment, handleInputChange, inputValue],
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

  const handleFavSearchChange = useCallback(
    (value: string) => {
      setFavSearchInput(value)
      if (favDebounceRef.current) clearTimeout(favDebounceRef.current)
      favDebounceRef.current = setTimeout(() => actions.setFilter({ favSearch: value }), 600)
    },
    [actions],
  )

  const toggleCategory = useCallback(
    (val: string | null) => {
      if (val === null) {
        actions.setFilter({ selectedCats: [] }) // "All"
        return
      }
      const cur = state.filters.selectedCats
      // Empty === all; first explicit pick starts from "all selected" minus none.
      const base = cur.length === 0 ? [...Object.keys(CATEGORY_META)] : cur
      const next = base.includes(val) ? base.filter((c) => c !== val) : [...base, val]
      // Selecting everything collapses back to "all" (empty).
      actions.setFilter({
        selectedCats: next.length === Object.keys(CATEGORY_META).length ? [] : next,
      })
    },
    [actions, state.filters.selectedCats],
  )

  const toggleAdvanced = useCallback(() => {
    const next = !showAdvanced
    setShowAdvanced(next)
    actions.setFilter({ advancedOpen: next })
  }, [showAdvanced, actions])

  const clearSearch = useCallback(() => {
    setInputValue('')
    if (debounceRef.current) clearTimeout(debounceRef.current)
    actions.commitQuery('')
    actions.setTab('popular')
  }, [actions])

  const navigateToGallery = useCallback(
    (g: EhGallery) => {
      const fav = tab === 'favorites' ? '?fav=1' : ''
      router.push(`/e-hentai/${g.gid}/${g.token}${fav}`)
    },
    [router, tab],
  )

  const handleSaveSearch = useCallback(async () => {
    const name = saveSearchName.trim() || query || 'Search'
    try {
      await api.savedSearches.create({
        name,
        query,
        params: serializeEhSavedSearchParams(state),
      })
      toast.success(t('browse.saveSearchSaved'))
      setSaveSearchName('')
      setShowSaveInput(false)
      refreshSavedSearches()
    } catch {
      toast.error(t('browse.saveSearchFailed'))
    }
  }, [saveSearchName, query, refreshSavedSearches, state])

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
      const identity = parseEhSavedSearch(s.query, s.params)
      setInputValue(identity.query)
      actions.applyIdentity(identity)
      setShowSavedSearches(false)
    },
    [actions],
  )

  const handleSubscribe = async () => {
    const subUrl = `https://e-hentai.org/?f_search=${encodeURIComponent(query)}`
    try {
      await createSub({
        url: subUrl,
        name: subName.trim() || query,
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

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex } = useGridKeyboard({
    totalItems: items.length,
    colCount,
    onEnter: (i) => {
      const g = items[i]
      if (g) navigateToGallery(g)
    },
    enabled: viewMode === 'grid',
  })

  const catAllActive = filters.selectedCats.length === 0
  const endLabel = tab === 'favorites' ? t('browse.noMoreFavorites') : t('browse.noMoreResults')

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
            {showHistory && autocompleteSuggestions.length === 0 && history.length > 0 && (
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
                      className="text-vault-text-muted hover:text-red-400 text-xs opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-opacity px-1"
                      title={t('common.remove')}
                    >
                      ✕
                    </span>
                  </button>
                ))}
              </div>
            )}
            {autocompleteFragment && (
              <SearchAutocompleteDropdown
                suggestions={autocompleteSuggestions}
                highlightedIndex={autocompleteHighlight}
                onSelect={handleAutocompleteSelect}
                onHighlight={setAutocompleteHighlight}
              />
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
                {query && (
                  <button
                    onClick={() => setShowSaveInput((v) => !v)}
                    className="text-xs text-vault-accent hover:text-vault-accent/80 transition-colors"
                  >
                    {t('browse.saveSearch')}
                  </button>
                )}
              </div>

              {/* Save current search input */}
              {showSaveInput && query && (
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
                        className="text-vault-text-muted hover:text-red-400 text-xs opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-opacity px-1 shrink-0"
                        title={t('common.delete')}
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
          {showHistory && autocompleteSuggestions.length === 0 && history.length > 0 && (
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
                    className="text-vault-text-muted hover:text-red-400 text-xs opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-opacity px-1"
                    title={t('common.remove')}
                  >
                    ✕
                  </span>
                </button>
              ))}
            </div>
          )}
          {autocompleteFragment && (
            <SearchAutocompleteDropdown
              suggestions={autocompleteSuggestions}
              highlightedIndex={autocompleteHighlight}
              onSelect={handleAutocompleteSelect}
              onHighlight={setAutocompleteHighlight}
            />
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
                {query && (
                  <button
                    onClick={() => setShowSaveInput((v) => !v)}
                    className="text-xs text-vault-accent hover:text-vault-accent/80 transition-colors"
                  >
                    {t('browse.saveSearch')}
                  </button>
                )}
              </div>

              {/* Save current search input */}
              {showSaveInput && query && (
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
                        className="text-vault-text-muted hover:text-red-400 text-xs opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-opacity px-1 shrink-0"
                        title={t('common.delete')}
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
        {query && (
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
                    value={`https://e-hentai.org/?f_search=${encodeURIComponent(query)}`}
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
                    placeholder={query}
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
            onClick={() => setViewModePersist('list')}
            title={t('browse.listView')}
            className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'list' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            ☰
          </button>
          <button
            onClick={() => setViewModePersist('grid')}
            title={t('browse.gridView')}
            className={`px-3 py-2.5 text-sm transition-colors ${viewMode === 'grid' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            ⊞
          </button>
        </div>
      </div>

      {/* ── Search mode: clear header (replaces tabs) ── */}
      {query && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-vault-text-secondary">
            {t('browse.resultsFor', { query })}
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
      {!query && (
        <div className="flex gap-1 border-b border-vault-border overflow-x-auto scrollbar-hide">
          <button
            onClick={() => actions.setTab('popular')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === 'popular'
                ? 'border-orange-400 text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.popularTab')}
          </button>
          <button
            onClick={() => actions.setTab('search')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === 'search'
                ? 'border-vault-accent text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.latestTab')}
          </button>
          <button
            onClick={() => actions.setTab('toplist')}
            className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === 'toplist'
                ? 'border-yellow-400 text-vault-text'
                : 'border-transparent text-vault-text-muted hover:text-vault-text'
            }`}
          >
            {t('browse.toplistTab')}
          </button>
          {ehConfigured && (
            <button
              onClick={() => actions.setTab('favorites')}
              className={`shrink-0 ml-3 md:ml-auto px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === 'favorites'
                  ? 'border-[#e91e63] text-vault-text'
                  : 'border-transparent text-vault-text-muted hover:text-vault-text'
              }`}
            >
              {t('browse.favoritesTab')}
            </button>
          )}
        </div>
      )}

      {/* ── Search/Latest sub-controls ── */}
      {isSearchView && (
        <>
          {/* Category filter row */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
            <button
              onClick={() => toggleCategory(null)}
              className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                catAllActive
                  ? 'bg-vault-text text-vault-bg border-vault-text'
                  : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
              }`}
            >
              {t('common.all')}
            </button>
            {CATEGORIES.map((cat) => {
              const isActive = !catAllActive && filters.selectedCats.includes(cat.value)
              return (
                <button
                  key={cat.value}
                  onClick={() => toggleCategory(cat.value)}
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
                >
                  {cat.label}
                </button>
              )
            })}
          </div>

          {/* Advanced Search toggle + panel */}
          <div>
            <button
              onClick={toggleAdvanced}
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
                      { bit: EH_ADVANCED_SEARCH_BITS.name, label: 'Name' },
                      { bit: EH_ADVANCED_SEARCH_BITS.tags, label: 'Tags' },
                      { bit: EH_ADVANCED_SEARCH_BITS.description, label: 'Description' },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.torrentFilenames,
                        label: 'Torrent Filenames',
                      },
                      { bit: EH_ADVANCED_SEARCH_BITS.onlyTorrents, label: 'Only Torrents' },
                    ].map(({ bit, label }) => (
                      <label
                        key={bit}
                        className="flex items-center gap-1.5 text-xs text-vault-text-secondary cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={!!(filters.advSearch & bit)}
                          onChange={() => actions.setFilter({ advSearch: filters.advSearch ^ bit })}
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
                      { bit: EH_ADVANCED_SEARCH_BITS.lowPowerTags, label: 'Low-Power Tags' },
                      { bit: EH_ADVANCED_SEARCH_BITS.downvotedTags, label: 'Downvoted Tags' },
                      { bit: EH_ADVANCED_SEARCH_BITS.showExpunged, label: 'Show Expunged' },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.disableLanguageFilter,
                        label: 'Disable Language Filter',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.disableUploaderFilter,
                        label: 'Disable Uploader Filter',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.disableTagFilter,
                        label: 'Disable Tag Filter',
                      },
                    ].map(({ bit, label }) => (
                      <label
                        key={bit}
                        className="flex items-center gap-1.5 text-xs text-vault-text-secondary cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={!!(filters.advSearch & bit)}
                          onChange={() => actions.setFilter({ advSearch: filters.advSearch ^ bit })}
                          className="rounded border-vault-border"
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Language + Min Rating + Page Range */}
                <div className="flex flex-wrap gap-4">
                  <div>
                    <p className="text-xs text-vault-text-muted mb-1">Language</p>
                    <select
                      value={filters.language}
                      onChange={(e) => actions.setFilter({ language: e.target.value })}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                    >
                      <option value="">Any language</option>
                      <option value="english">English</option>
                      <option value="chinese">Chinese</option>
                      <option value="japanese">Japanese</option>
                      <option value="korean">Korean</option>
                      <option value="spanish">Spanish</option>
                      <option value="french">French</option>
                      <option value="german">German</option>
                      <option value="russian">Russian</option>
                    </select>
                  </div>
                  <div>
                    <p className="text-xs text-vault-text-muted mb-1">{t('browse.minRating')}</p>
                    <select
                      value={filters.minRating ?? ''}
                      onChange={(e) =>
                        actions.setFilter({
                          minRating: e.target.value ? Number(e.target.value) : null,
                        })
                      }
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
                        value={filters.pageFrom ?? ''}
                        onChange={(e) =>
                          actions.setFilter({
                            pageFrom: e.target.value ? Number(e.target.value) : null,
                          })
                        }
                        placeholder={t('browse.pageFrom')}
                        className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                      />
                      <span className="text-vault-text-muted text-xs">-</span>
                      <input
                        type="number"
                        value={filters.pageTo ?? ''}
                        onChange={(e) =>
                          actions.setFilter({
                            pageTo: e.target.value ? Number(e.target.value) : null,
                          })
                        }
                        placeholder={t('browse.pageTo')}
                        className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                      />
                    </div>
                  </div>
                </div>

                {/* Reset */}
                <button
                  onClick={() =>
                    actions.setFilter({
                      advSearch: 0,
                      minRating: null,
                      pageFrom: null,
                      pageTo: null,
                      language: '',
                      selectedCats: [],
                    })
                  }
                  className="text-xs text-vault-text-muted hover:text-vault-text transition-colors"
                >
                  {t('browse.resetAdvanced')}
                </button>
              </div>
            )}
          </div>

          {/* Results header */}
          {total !== null && (
            <div className="flex items-center justify-between text-xs text-vault-text-muted">
              <span>
                {query
                  ? t('browse.resultsFor', { query })
                  : t('browse.resultsCount', { count: total.toLocaleString() })}
              </span>
              {query && (
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
            </div>
          )}
        </>
      )}

      {/* ── Favorites sub-controls ── */}
      {!query && tab === 'favorites' && ehConfigured && (
        <>
          {/* Favorites category pills (All + 0-9) */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
            <button
              onClick={() => actions.setFilter({ favCat: 'all' })}
              className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                filters.favCat === 'all'
                  ? 'bg-vault-text text-vault-bg border-vault-text'
                  : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
              }`}
            >
              {t('common.all')}
            </button>
            {Array.from({ length: 10 }, (_, i) => {
              const catData = favCategories.find((c) => c.index === i)
              const name = catData?.name || `Favorites ${i}`
              const color = FAV_COLORS[i]
              const isActive = filters.favCat === String(i)
              return (
                <button
                  key={i}
                  onClick={() => actions.setFilter({ favCat: String(i) })}
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
            value={favSearchInput}
            onChange={(e) => handleFavSearchChange(e.target.value)}
            placeholder={t('browse.filterFavorites')}
            className="w-full bg-vault-card border border-vault-border rounded-lg px-4 py-2 text-sm
                     text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors"
          />

          {total !== null && (
            <div className="flex items-center justify-between text-xs text-vault-text-muted">
              <span>
                {total.toLocaleString()} {t('browse.favorited')}
                {filters.favSearch && ` ${t('browse.matchingQuery', { query: filters.favSearch })}`}
              </span>
            </div>
          )}
        </>
      )}

      {/* ── Toplist sub-controls ── */}
      {!query && tab === 'toplist' && (
        <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
          {TOPLIST_OPTIONS.map(({ tl, label }) => (
            <button
              key={tl}
              onClick={() => actions.setFilter({ toplistTl: tl })}
              className={`shrink-0 px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                filters.toplistTl === tl
                  ? 'bg-yellow-500 text-black border-yellow-500'
                  : 'bg-transparent text-vault-text-secondary border-vault-border hover:border-vault-border-hover hover:text-vault-text'
              }`}
            >
              {t(label)}
            </button>
          ))}
        </div>
      )}

      {/* ── Popular header ── */}
      {!query && tab === 'popular' && total !== null && (
        <div className="text-xs text-vault-text-muted">
          {items.length} {t('browse.results')}
        </div>
      )}

      {/* ════════ UNIFIED RESULTS ════════ */}

      {/* Loading (only when no data yet) */}
      {seeding && items.length === 0 && (
        <div className="flex justify-center py-4">
          <LoadingSpinner />
        </div>
      )}

      {/* Error (empty list — mid-list errors surface below the grid instead) */}
      {state.error && !loading && items.length === 0 && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
          {state.error.includes('credentials not configured') || state.error.includes('503') ? (
            <p className="text-yellow-400">{t('browse.credentialsMissingDetail')}</p>
          ) : (
            <p className="text-red-400">{state.error || t('browse.failedLoadResults')}</p>
          )}
        </div>
      )}

      {/* Gallery grid / list */}
      {items.length > 0 && (
        <>
          {viewMode === 'list' ? (
            <div className="space-y-2">
              {items.map((g) => (
                <ListCard
                  key={`${g.gid}-${g.token}`}
                  gallery={g}
                  status={browseStatuses[String(g.gid)]}
                  onClick={() => navigateToGallery(g)}
                />
              ))}
            </div>
          ) : (
            <VirtualGrid
              items={items}
              columns={{ base: 3, sm: 4, md: 5, lg: 6, xl: 7, xxl: 8 }}
              gap={8}
              estimateHeight={220}
              focusedIndex={focusedIndex}
              onColCountChange={setColCount}
              renderItem={(g) => (
                <GridCard
                  key={`${g.gid}-${g.token}`}
                  gallery={g}
                  status={browseStatuses[String(g.gid)]}
                  onClick={() => navigateToGallery(g)}
                />
              )}
              onLoadMore={state.hasMore && state.status !== 'error' ? loadMore : undefined}
              hasMore={state.hasMore}
              isLoading={loading}
            />
          )}

          {/* Mid-list load failure: the top banner is scrolled far out of view here,
              so surface the error + manual retry where the user is actually looking. */}
          {state.error && !loading && (
            <div className="flex flex-col items-center gap-2 py-4">
              <span className="text-xs text-red-400">{t('browse.failedLoadResults')}</span>
              <button
                onClick={() => loadMore()}
                className="px-4 py-1.5 rounded-full text-xs font-medium border border-vault-border text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text transition-colors"
              >
                {t('common.retry')}
              </button>
            </div>
          )}

          {/* End indicator */}
          {!state.hasMore && (
            <div className="flex justify-center py-4">
              <span className="text-xs text-vault-text-muted">{endLabel}</span>
            </div>
          )}
        </>
      )}

      {/* Empty state */}
      {!loading && !state.error && items.length === 0 && state.status === 'idle' && (
        <div className="text-center py-20 text-vault-text-muted">{t('browse.noResults')}</div>
      )}
    </div>
  )
}
