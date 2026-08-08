'use client'

import {
  useState,
  useRef,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  Suspense,
} from 'react'
import { useRouter } from 'next/navigation'
import { useEhBrowse } from '@/hooks/useEhBrowse'
import { useProfile } from '@/hooks/useProfile'
import {
  EH_ADVANCED_SEARCH_BITS,
  initialFilters,
  parseEhSavedSearch,
  queryKey,
  serializeEhSavedSearchParams,
  toggleSelectedCategory,
} from '@/lib/ehBrowseState'
import {
  applyEhAutocompleteSuggestion,
  getEhAutocompleteFragment,
} from '@/lib/ehSearchAutocomplete'
import { useCreateSubscription, useSubscriptions } from '@/hooks/useSubscriptions'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { decideAnchorRestore, type BrowseAnchor } from '@/lib/browse/anchor'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'

import { LoadingSpinner } from '@/components/LoadingSpinner'
import { VirtualGrid } from '@/components/VirtualGrid'
import { CredentialBanner } from '@/components/CredentialBanner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { CATEGORY_META, GridCard, isLightColor, ListCard } from '@/components/eh/EhBrowseCards'
import {
  Search as SearchIcon,
  X as XIcon,
  ChevronDown,
  ChevronUp,
  Bookmark,
  BookmarkCheck,
  Rss,
  Shuffle,
  Camera,
} from 'lucide-react'
import type { EhGallery, SavedSearch, TagItem } from '@/lib/types'

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
  { label: 'browse.cron.everyHour', value: '0 * * * *' },
  { label: 'browse.cron.every2Hours', value: '0 */2 * * *' },
  { label: 'browse.cron.every6Hours', value: '0 */6 * * *' },
  { label: 'browse.cron.daily', value: '0 0 * * *' },
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
  const { data: profile } = useProfile()
  const browseUserId = profile?.username
  const {
    state,
    actions,
    loadMore,
    favCategories,
    restoreInstruction,
    acknowledgeRestore,
  } = useEhBrowse({ userId: browseUserId })

  // ── Local UI state (not part of query identity) ──
  const [inputValue, setInputValue] = useState(state.query)
  const [favSearchInput, setFavSearchInput] = useState(state.filters.favSearch)
  const [viewMode, setViewMode] = useState<ViewMode>(getInitialViewMode)
  const setViewModePersist = useCallback((m: ViewMode) => {
    setViewMode(m)
    if (typeof window !== 'undefined') localStorage.setItem(VIEW_MODE_KEY, m)
  }, [])
  const [colCount, setColCount] = useState(3)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const favDebounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const imageSearchAbortRef = useRef<AbortController | null>(null)
  const itemElementsRef = useRef(new Map<number, HTMLElement>())
  const visibleStartRef = useRef(0)
  const layoutRef = useRef<BrowseLayoutSnapshot>({ columns: 3, width: 0, mode: viewMode })
  const pendingRestoreRef = useRef<{
    key: string
    identityKey: string
    index: number
    offset: number
  } | null>(null)
  const [restoreRequest, setRestoreRequest] = useState<{
    key: string
    identityKey: string
    index: number
  }>()

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
  const { data: watchedData, mutate: refreshWatched } = useSubscriptions({
    source: 'ehentai',
    enabled: true,
    limit: 50,
  })
  const watchedSearches = watchedData?.subscriptions ?? []

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
  const autocompleteSuggestions = useMemo(
    () => (Array.isArray(autocompleteData) ? autocompleteData : []),
    [autocompleteData],
  )

  // Mobile search expand
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false)
  const mobileInputRef = useRef<HTMLInputElement>(null)
  const mobileSavedSearchesRef = useRef<HTMLDivElement>(null)
  const [showImageSearch, setShowImageSearch] = useState(false)
  const [imageSearchFile, setImageSearchFile] = useState<File | null>(null)
  const [imageSearchSimilar, setImageSearchSimilar] = useState(true)
  const [imageSearchCovers, setImageSearchCovers] = useState(false)
  const [imageSearchExpunged, setImageSearchExpunged] = useState(false)
  const [imageSearchLoading, setImageSearchLoading] = useState(false)

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
  const seedKey = queryKey(state)
  // A pending input timer belongs to the identity in which it was created. A
  // popstate, saved-search, or tab transition must invalidate it before it can
  // overwrite the newly supplied URL.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (favDebounceRef.current) clearTimeout(favDebounceRef.current)
  }, [seedKey])
  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (favDebounceRef.current) clearTimeout(favDebounceRef.current)
      imageSearchAbortRef.current?.abort()
    },
    [],
  )
  useEffect(() => {
    if (!browseUserId || items.length !== 0 || !state.hasMore || state.status !== 'idle') return
    // Favorites requires credentials. Deferring one task lets the coordinator's
    // restore effect hydrate an existing snapshot before a seed request races it.
    if (tab === 'favorites' && !ehConfigured) return
    const timer = setTimeout(() => void loadMore(), 0)
    return () => clearTimeout(timer)
  }, [browseUserId, ehConfigured, items.length, loadMore, seedKey, state.hasMore, state.status, tab])

  const previousRestoreIdentityRef = useRef(seedKey)
  const handledRestoreKeyRef = useRef<string | null>(null)
  const scheduledRestoreKeyRef = useRef<string | null>(null)
  useEffect(() => {
    if (previousRestoreIdentityRef.current === seedKey) return
    previousRestoreIdentityRef.current = seedKey
    pendingRestoreRef.current = null
    setRestoreRequest(undefined)
  }, [seedKey])
  useEffect(() => {
    if (!restoreInstruction || restoreInstruction.identityKey !== seedKey) {
      if (pendingRestoreRef.current) {
        pendingRestoreRef.current = null
        setRestoreRequest(undefined)
      }
      return
    }
    if (handledRestoreKeyRef.current === restoreInstruction.key) return
    if (restoreInstruction.target.kind === 'top') {
      if (pendingRestoreRef.current) {
        pendingRestoreRef.current = null
        setRestoreRequest(undefined)
      }
      if (scheduledRestoreKeyRef.current === restoreInstruction.key) return
      scheduledRestoreKeyRef.current = restoreInstruction.key
      const frame = requestAnimationFrame(() => {
        window.scrollTo(0, 0)
        handledRestoreKeyRef.current = restoreInstruction.key
        scheduledRestoreKeyRef.current = null
        acknowledgeRestore(restoreInstruction.key)
      })
      return () => {
        cancelAnimationFrame(frame)
        if (scheduledRestoreKeyRef.current === restoreInstruction.key)
          scheduledRestoreKeyRef.current = null
      }
    }
    const anchor = restoreInstruction.target.view.anchor
    if (!anchor) {
      if (pendingRestoreRef.current) {
        pendingRestoreRef.current = null
        setRestoreRequest(undefined)
      }
      if (scheduledRestoreKeyRef.current === restoreInstruction.key) return
      scheduledRestoreKeyRef.current = restoreInstruction.key
      const frame = requestAnimationFrame(() => {
        window.scrollTo(0, 0)
        handledRestoreKeyRef.current = restoreInstruction.key
        scheduledRestoreKeyRef.current = null
        acknowledgeRestore(restoreInstruction.key)
      })
      return () => {
        cancelAnimationFrame(frame)
        if (scheduledRestoreKeyRef.current === restoreInstruction.key)
          scheduledRestoreKeyRef.current = null
      }
    }
    const decision = decideAnchorRestore(anchor, items, (gallery) => gallery.gid)
    if (decision.kind === 'anchor' && viewMode === 'grid') {
      const nextPending = {
        key: restoreInstruction.key,
        identityKey: seedKey,
        index: decision.index,
        offset: decision.offset,
      }
      const pending = pendingRestoreRef.current
      if (
        pending?.key === nextPending.key &&
        pending.identityKey === nextPending.identityKey &&
        pending.index === nextPending.index &&
        pending.offset === nextPending.offset
      )
        return
      pendingRestoreRef.current = nextPending
      setRestoreRequest({
        key: restoreInstruction.key,
        identityKey: seedKey,
        index: decision.index,
      })
      return
    }
    if (pendingRestoreRef.current) {
      pendingRestoreRef.current = null
      setRestoreRequest(undefined)
    }
    if (scheduledRestoreKeyRef.current === restoreInstruction.key) return
    scheduledRestoreKeyRef.current = restoreInstruction.key
    const frame = requestAnimationFrame(() => {
      if (decision.kind === 'anchor') {
        const item = items[decision.index]
        const element = item ? itemElementsRef.current.get(item.gid) : null
        if (element) {
          window.scrollTo(0, window.scrollY + element.getBoundingClientRect().top - decision.offset)
          handledRestoreKeyRef.current = restoreInstruction.key
          scheduledRestoreKeyRef.current = null
          acknowledgeRestore(restoreInstruction.key)
          return
        }
      }
      if (decision.kind === 'pixel') window.scrollTo(0, decision.scrollY)
      else if (decision.kind === 'top') window.scrollTo(0, 0)
      else window.scrollTo(0, anchor.scrollY)
      handledRestoreKeyRef.current = restoreInstruction.key
      scheduledRestoreKeyRef.current = null
      acknowledgeRestore(restoreInstruction.key)
    })
    return () => {
      cancelAnimationFrame(frame)
      if (scheduledRestoreKeyRef.current === restoreInstruction.key)
        scheduledRestoreKeyRef.current = null
    }
  }, [acknowledgeRestore, items, restoreInstruction, seedKey, viewMode])

  const handleGridRestoreApplied = useCallback(
    (request: { key: string; index: number }) => {
      const pending = pendingRestoreRef.current
      if (
        !pending ||
        handledRestoreKeyRef.current === request.key ||
        pending.identityKey !== seedKey ||
        pending.key !== request.key ||
        pending.index !== request.index
      )
        return
      const item = items[request.index]
      const element = item ? itemElementsRef.current.get(item.gid) : null
      if (!element) return
      window.scrollTo(0, window.scrollY + element.getBoundingClientRect().top - pending.offset)
      pendingRestoreRef.current = null
      setRestoreRequest(undefined)
      handledRestoreKeyRef.current = pending.key
      acknowledgeRestore(pending.key)
    },
    [acknowledgeRestore, items, seedKey],
  )

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
      actions.setFilter({
        selectedCats: toggleSelectedCategory(state.filters.selectedCats, val),
      })
    },
    [actions, state.filters.selectedCats],
  )

  const toggleAdvanced = useCallback(() => {
    actions.setFilter({ advancedOpen: !filters.advancedOpen })
  }, [actions, filters.advancedOpen])

  const clearSearch = useCallback(() => {
    setInputValue('')
    if (debounceRef.current) clearTimeout(debounceRef.current)
    actions.reset()
  }, [actions])

  const captureAnchor = useCallback(
    (preferred?: EhGallery): BrowseAnchor => {
      const fallbackIndex = Math.min(visibleStartRef.current, Math.max(0, items.length - 1))
      const listAnchor =
        viewMode === 'list'
          ? items.find((item) => {
              const rect = itemElementsRef.current.get(item.gid)?.getBoundingClientRect()
              return !!rect && rect.bottom > 0
            })
          : items[fallbackIndex]
      const gallery = preferred ?? listAnchor
      const element = gallery ? itemElementsRef.current.get(gallery.gid) : null
      return {
        itemId: gallery?.gid ?? null,
        offset: element?.getBoundingClientRect().top ?? 0,
        scrollY: window.scrollY,
      }
    },
    [items, viewMode],
  )

  // `captureAnchor` is rebuilt whenever `items` changes, so the scroll
  // subscription below must not depend on it directly: an append that commits
  // before a scheduled capture frame fires would tear the effect down, cancel
  // the frame, and drop that scroll position without rescheduling it. Infinite
  // scroll makes that window routine, since scrolling is what triggers the
  // append. Read the current implementation through a ref instead, and keep the
  // subscription alive for the page's whole lifetime.
  const captureAnchorRef = useRef(captureAnchor)
  useLayoutEffect(() => {
    captureAnchorRef.current = captureAnchor
  }, [captureAnchor])

  // This page is the sole owner of the E-Hentai scroll lifecycle: capture the
  // full logical anchor cheaply, then persist after settling or lifecycle exit.
  useEffect(() => {
    let frame: number | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let latestAnchor: BrowseAnchor | null = null
    const save = () => {
      if (pendingRestoreRef.current) return
      const anchor = latestAnchor ?? captureAnchorRef.current()
      actions.checkpoint(anchor, layoutRef.current)
    }
    const capture = () => {
      frame = undefined
      if (pendingRestoreRef.current) return
      latestAnchor = captureAnchorRef.current()
      actions.setAnchor(latestAnchor)
      clearTimeout(timer)
      timer = setTimeout(save, 250)
    }
    const onScroll = () => {
      if (frame === undefined) frame = requestAnimationFrame(capture)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('pagehide', save)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('pagehide', save)
      if (frame !== undefined) cancelAnimationFrame(frame)
      clearTimeout(timer)
    }
  }, [actions])

  const openItem = useCallback(
    (g: EhGallery) => {
      actions.checkpoint(captureAnchor(g), layoutRef.current)
      const fav = tab === 'favorites' ? '?fav=1' : ''
      router.push(`/e-hentai/${g.gid}/${g.token}${fav}`)
    },
    [actions, captureAnchor, router, tab],
  )

  const searchUploader = useCallback(
    (uploader: string) => {
      const value = `uploader:${uploader.includes(' ') ? `"${uploader}"` : uploader}`
      setInputValue(value)
      commitSearch(value)
    },
    [commitSearch],
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
      void refreshWatched()
      setShowSubscribe(false)
      setSubName('')
    } catch {
      toast.error(t('browse.subscribeFailed'))
    }
  }

  const openWatchedSearch = useCallback(
    (url: string) => {
      try {
        const value = new URL(url).searchParams.get('f_search') || ''
        if (!value) return
        setInputValue(value)
        commitSearch(value)
      } catch {
        toast.error(t('browse.failedLoadResults'))
      }
    },
    [commitSearch],
  )

  const openRandomLoadedGallery = useCallback(() => {
    if (items.length === 0) return
    const gallery = items[Math.floor(Math.random() * items.length)]
    openItem(gallery)
  }, [items, openItem])

  const submitImageSearch = useCallback(async () => {
    if (!imageSearchFile) return
    imageSearchAbortRef.current?.abort()
    const controller = new AbortController()
    imageSearchAbortRef.current = controller
    setImageSearchLoading(true)
    try {
      const result = await api.eh.imageSearch(
        imageSearchFile,
        {
          similar: imageSearchSimilar,
          covers: imageSearchCovers,
          expunged: imageSearchExpunged,
        },
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      setInputValue('')
      actions.showExternalResults(result.galleries, result.total)
      setShowImageSearch(false)
      setImageSearchFile(null)
      toast.success(t('browse.imageSearchResults', { count: result.total.toLocaleString() }))
    } catch (error) {
      if (controller.signal.aborted) return
      toast.error(error instanceof Error ? error.message : t('browse.failedLoadResults'))
    } finally {
      if (imageSearchAbortRef.current === controller) setImageSearchLoading(false)
    }
  }, [actions, imageSearchCovers, imageSearchExpunged, imageSearchFile, imageSearchSimilar])

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex } = useGridKeyboard({
    totalItems: items.length,
    colCount,
    onEnter: (i) => {
      const g = items[i]
      if (g) openItem(g)
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
                  <div key={q} className="group flex w-full items-center hover:bg-vault-card-hover">
                    <button
                      type="button"
                      onClick={() => {
                        handleHistorySelect(q)
                        setMobileSearchOpen(false)
                      }}
                      className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm text-vault-text transition-colors"
                    >
                      <span className="text-vault-text-muted text-xs">&#x1F50D;</span>
                      <span className="flex-1 truncate">{q}</span>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => handleHistoryRemove(q, e)}
                      className="px-3 py-2 text-xs text-vault-text-muted opacity-100 transition-opacity hover:text-red-400 can-hover:opacity-0 can-hover:group-hover:opacity-100"
                      aria-label={t('common.remove')}
                      title={t('common.remove')}
                    >
                      ✕
                    </button>
                  </div>
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
          type="button"
          onClick={() => setShowImageSearch(true)}
          title={t('browse.searchByImage')}
          aria-label={t('browse.searchByImage')}
          className="p-2.5 rounded-lg border border-vault-border text-vault-text-muted hover:text-vault-text hover:border-vault-border-hover transition-colors"
        >
          <Camera size={16} />
        </button>

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
                    <div
                      key={s.id}
                      className="group flex w-full items-center hover:bg-vault-card-hover"
                    >
                      <button
                        type="button"
                        onClick={() => handleLoadSavedSearch(s)}
                        className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm text-vault-text transition-colors"
                      >
                        <span className="flex-1 truncate text-xs">{s.name}</span>
                        {s.query && (
                          <span className="max-w-[80px] truncate text-[10px] text-vault-text-muted">
                            {s.query}
                          </span>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteSavedSearch(s.id, e)}
                        className="shrink-0 px-3 py-2 text-xs text-vault-text-muted opacity-100 transition-opacity hover:text-red-400 can-hover:opacity-0 can-hover:group-hover:opacity-100"
                        aria-label={t('common.delete')}
                        title={t('common.delete')}
                      >
                        ✕
                      </button>
                    </div>
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
                <div key={q} className="group flex w-full items-center hover:bg-vault-card-hover">
                  <button
                    type="button"
                    onClick={() => handleHistorySelect(q)}
                    className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm text-vault-text transition-colors"
                  >
                    <span className="text-vault-text-muted text-xs">&#x1F50D;</span>
                    <span className="flex-1 truncate">{q}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => handleHistoryRemove(q, e)}
                    className="px-3 py-2 text-xs text-vault-text-muted opacity-100 transition-opacity hover:text-red-400 can-hover:opacity-0 can-hover:group-hover:opacity-100"
                    aria-label={t('common.remove')}
                    title={t('common.remove')}
                  >
                    ✕
                  </button>
                </div>
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
                    <div
                      key={s.id}
                      className="group flex w-full items-center hover:bg-vault-card-hover"
                    >
                      <button
                        type="button"
                        onClick={() => handleLoadSavedSearch(s)}
                        className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm text-vault-text transition-colors"
                      >
                        <span className="flex-1 truncate text-xs">{s.name}</span>
                        {s.query && (
                          <span className="max-w-[80px] truncate text-[10px] text-vault-text-muted">
                            {s.query}
                          </span>
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteSavedSearch(s.id, e)}
                        className="shrink-0 px-3 py-2 text-xs text-vault-text-muted opacity-100 transition-opacity hover:text-red-400 can-hover:opacity-0 can-hover:group-hover:opacity-100"
                        aria-label={t('common.delete')}
                        title={t('common.delete')}
                      >
                        ✕
                      </button>
                    </div>
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
                          {t(p.label)}
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

        <button
          type="button"
          onClick={openRandomLoadedGallery}
          disabled={items.length === 0}
          title={t('browse.openRandom')}
          aria-label={t('browse.openRandom')}
          className="p-2.5 rounded-lg border border-vault-border text-vault-text-muted hover:text-vault-text hover:border-vault-border-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Shuffle size={16} />
        </button>

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

      {showImageSearch && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t('browse.searchByImage')}
          className="rounded-lg border border-vault-border bg-vault-card p-4 space-y-3"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-vault-text">{t('browse.searchByImage')}</h2>
            <button
              type="button"
              onClick={() => setShowImageSearch(false)}
              className="text-vault-text-muted hover:text-vault-text"
              aria-label={t('common.close')}
            >
              <XIcon size={16} />
            </button>
          </div>
          <input
            type="file"
            accept="image/jpeg,.jpg,.jpeg"
            onChange={(event) => setImageSearchFile(event.target.files?.[0] ?? null)}
            className="block w-full text-xs text-vault-text-secondary file:mr-3 file:rounded file:border-0 file:bg-vault-input file:px-3 file:py-2 file:text-vault-text"
          />
          <p className="text-xs text-vault-text-muted">{t('browse.imageOriginalJpeg')}</p>
          <div className="flex flex-wrap gap-4 text-xs text-vault-text-secondary">
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={imageSearchSimilar}
                onChange={(event) => setImageSearchSimilar(event.target.checked)}
              />
              {t('browse.similarityScan')}
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={imageSearchCovers}
                onChange={(event) => setImageSearchCovers(event.target.checked)}
              />
              {t('browse.coversOnly')}
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={imageSearchExpunged}
                onChange={(event) => setImageSearchExpunged(event.target.checked)}
              />
              {t('browse.includeExpunged')}
            </label>
          </div>
          <button
            type="button"
            onClick={submitImageSearch}
            disabled={!imageSearchFile || imageSearchLoading}
            className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {imageSearchLoading ? t('common.loading') : t('browse.search')}
          </button>
        </div>
      )}

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
            type="button"
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
            type="button"
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
            type="button"
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
              type="button"
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

      {watchedSearches.length > 0 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide">
          <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-vault-text-muted">
            {t('browse.watched')}
          </span>
          {watchedSearches.map((subscription) => (
            <button
              key={subscription.id}
              type="button"
              onClick={() => openWatchedSearch(subscription.url)}
              className="shrink-0 max-w-56 truncate rounded-full border border-vault-border bg-vault-card px-3 py-1 text-xs text-vault-text-secondary hover:border-vault-accent hover:text-vault-accent transition-colors"
              title={subscription.name || subscription.url}
            >
              {subscription.name || subscription.url}
            </button>
          ))}
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
                  {t(cat.label)}
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
              {filters.advancedOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>

            {filters.advancedOpen && (
              <div className="mt-2 bg-vault-card border border-vault-border rounded-lg p-4 space-y-4">
                {/* Search in */}
                <div>
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    {t('browse.searchIn')}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { bit: EH_ADVANCED_SEARCH_BITS.name, label: 'browse.searchName' },
                      { bit: EH_ADVANCED_SEARCH_BITS.tags, label: 'browse.searchTags' },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.description,
                        label: 'browse.searchDescription',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.torrentFilenames,
                        label: 'browse.torrentFilenames',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.onlyTorrents,
                        label: 'browse.onlyTorrents',
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
                        {t(label)}
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
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.lowPowerTags,
                        label: 'browse.lowPowerTags',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.downvotedTags,
                        label: 'browse.downvotedTags',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.showExpunged,
                        label: 'browse.showExpunged',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.disableLanguageFilter,
                        label: 'browse.disableLanguageFilter',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.disableUploaderFilter,
                        label: 'browse.disableUploaderFilter',
                      },
                      {
                        bit: EH_ADVANCED_SEARCH_BITS.disableTagFilter,
                        label: 'browse.disableTagFilter',
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
                        {t(label)}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Language + Min Rating + Page Range */}
                <div className="flex flex-wrap gap-4">
                  <div>
                    <p className="text-xs text-vault-text-muted mb-1">{t('browse.language')}</p>
                    <select
                      value={filters.language}
                      onChange={(e) => actions.setFilter({ language: e.target.value })}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none"
                    >
                      <option value="">{t('browse.anyLanguage')}</option>
                      <option value="english">{t('browse.language.english')}</option>
                      <option value="chinese">{t('browse.language.chinese')}</option>
                      <option value="japanese">{t('browse.language.japanese')}</option>
                      <option value="korean">{t('browse.language.korean')}</option>
                      <option value="spanish">{t('browse.language.spanish')}</option>
                      <option value="french">{t('browse.language.french')}</option>
                      <option value="german">{t('browse.language.german')}</option>
                      <option value="russian">{t('browse.language.russian')}</option>
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
          {typeof total === 'number' && (
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
              // Favourite category names are remote E-Hentai data, not UI copy — the
              // fallback mirrors E-Hentai's own default label so it does not flip
              // languages once the real names arrive.
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

          {typeof total === 'number' && (
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
      {!query && tab === 'popular' && typeof total === 'number' && (
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

      {state.status === 'expired' && (
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-lg border border-vault-border bg-vault-card p-6 text-center"
        >
          <p className="font-medium text-vault-text">{t('error.session_expired')}</p>
          <p className="text-sm text-vault-text-muted">{t('browse.imageSessionExpiredHelp')}</p>
          <button
            type="button"
            className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-white hover:bg-vault-accent/90"
            onClick={() =>
              actions.commitIdentity(
                { tab: 'search', query: '', filters: initialFilters },
                'replace',
              )
            }
          >
            {t('browse.startNewSearch')}
          </button>
        </div>
      )}

      {/* Gallery grid / list */}
      {items.length > 0 && (
        <>
          {viewMode === 'list' ? (
            <div className="space-y-2">
              {items.map((g) => (
                <div
                  key={`${g.gid}-${g.token}`}
                  ref={(element) => {
                    if (element) itemElementsRef.current.set(g.gid, element)
                    else itemElementsRef.current.delete(g.gid)
                  }}
                >
                  <ListCard
                    gallery={g}
                    status={browseStatuses[String(g.gid)]}
                    onClick={() => openItem(g)}
                    onUploaderClick={() => searchUploader(g.uploader)}
                  />
                </div>
              ))}
            </div>
          ) : (
            <VirtualGrid
              items={items}
              getItemKey={(gallery) => gallery.gid}
              columns={{ base: 3, sm: 4, md: 5, lg: 6, xl: 7, xxl: 8 }}
              gap={8}
              estimateHeight={220}
              focusedIndex={focusedIndex}
              onColCountChange={setColCount}
              onRegisterElement={(index, element) => {
                const gallery = items[index]
                if (!gallery) return
                if (element) itemElementsRef.current.set(gallery.gid, element)
                else itemElementsRef.current.delete(gallery.gid)
              }}
              onVisibleRangeChange={({ startIndex }) => {
                visibleStartRef.current = startIndex
              }}
              onLayoutChange={({ colCount: columns, containerWidth }) => {
                const layout = { columns, width: containerWidth, mode: viewMode }
                layoutRef.current = layout
                actions.setLayout(layout)
              }}
              restoreRequest={
                restoreRequest?.identityKey === seedKey ? restoreRequest : undefined
              }
              onRestoreApplied={handleGridRestoreApplied}
              renderItem={(g) => (
                <GridCard
                  key={`${g.gid}-${g.token}`}
                  gallery={g}
                  status={browseStatuses[String(g.gid)]}
                  onClick={() => openItem(g)}
                  onUploaderClick={() => searchUploader(g.uploader)}
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
