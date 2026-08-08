'use client'

import {
  useState,
  useCallback,
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from 'react'
import { useRouter } from 'next/navigation'
import {
  BookOpen,
  X,
  ChevronDown,
  LayoutGrid,
  List,
  Bookmark,
  BookmarkCheck,
  HelpCircle,
} from 'lucide-react'
import { useGalleryCategories, useLibrarySources } from '@/hooks/useGalleries'
import type { Gallery } from '@/lib/types'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useLibraryBrowseSession } from '@/hooks/useLibraryBrowseSession'
import { useCollections } from '@/hooks/useCollections'
import { useAddDatasetMembers, useDatasets } from '@/hooks/useDatasets'
import { useProfile } from '@/hooks/useProfile'
import { useUnifiedSearch } from '@/hooks/useUnifiedSearch'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { GalleryListCard } from '@/components/GalleryListCard'
import { SkeletonGrid } from '@/components/Skeleton'
import { EmptyState } from '@/components/EmptyState'
import { VirtualGrid } from '@/components/VirtualGrid'
import { t, formatNumber } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { galleryHref } from '@/lib/galleryRoutes'
import type { SearchGalleryItem } from '@/lib/api'
import { decideAnchorRestore, type BrowseAnchor } from '@/lib/browse/anchor'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'
import {
  estimateLibraryGridRowHeight,
  getLibraryGridColumns,
  getLibraryGridGap,
} from '@/lib/libraryLayout'
import { useDisplayPreferences } from '@/hooks/useDisplayPreferences'

const SORT_OPTIONS = [
  { value: 'added_at', label: () => t('library.dateAdded') },
  { value: 'posted_at', label: () => t('library.datePosted') },
  { value: 'rating', label: () => t('library.rating') },
  { value: 'pages', label: () => t('library.pagesSort') },
  { value: 'title', label: () => t('library.titleSort') },
] as const

function mapSearchItemToGallery(item: SearchGalleryItem): Gallery {
  return {
    id: item.id,
    title: item.title,
    title_jpn: item.title_jpn ?? '',
    source: item.source,
    source_id: item.source_id,
    category: item.category ?? '',
    language: item.language ?? '',
    pages: item.pages,
    rating: item.rating,
    favorited: item.favorited,
    is_favorited: item.is_favorited,
    my_rating: item.my_rating,
    in_reading_list: item.in_reading_list,
    uploader: item.uploader ?? '',
    artist_id: item.artist_id,
    artist_name: item.artist_name,
    download_status: item.download_status as Gallery['download_status'],
    added_at: item.added_at ?? '',
    posted_at: item.posted_at,
    tags_array: item.tags_array ?? item.tags,
    cover_thumb: item.cover_thumb ?? null,
    import_mode: item.import_mode,
    source_url: item.source_url,
  }
}

function LibraryContent() {
  const router = useRouter()

  const {
    rawQuery,
    inputValue,
    parsed,
    setFilter,
    commitSearch,
    handleInputChange,
    selectMode,
    setSelectMode,
    selectedIds,
    setSelectedIds,
  } = useUnifiedSearch()

  const { data: categoriesData } = useGalleryCategories()
  const { data: sourcesData } = useLibrarySources()

  const [colCount, setColCount] = useState(4)
  const [batchTagMode, setBatchTagMode] = useState<'add' | 'remove' | null>(null)
  const [batchTagInput, setBatchTagInput] = useState('')
  const [batchTagList, setBatchTagList] = useState<string[]>([])
  const [syntaxHelpOpen, setSyntaxHelpOpen] = useState(false)
  const displayPreferences = useDisplayPreferences()
  const gridColumns = useMemo(
    () =>
      getLibraryGridColumns(
        displayPreferences.gallery_grid_density,
        displayPreferences.gallery_grid_columns,
      ),
    [displayPreferences.gallery_grid_columns, displayPreferences.gallery_grid_density],
  )

  // View mode: 'grid' | 'list', persisted to localStorage
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(() => {
    if (typeof window === 'undefined') return 'grid'
    return (localStorage.getItem('library_view_mode') as 'grid' | 'list') ?? 'grid'
  })

  const handleViewModeChange = useCallback((mode: 'grid' | 'list') => {
    setViewMode(mode)
    localStorage.setItem('library_view_mode', mode)
  }, [])

  // Collapsible filter panel: collapsed by default on mobile, expanded on desktop
  const [filtersOpen, setFiltersOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true
    return window.innerWidth >= 1024
  })

  // Keep filtersOpen in sync when window crosses lg breakpoint on resize
  useEffect(() => {
    function onResize() {
      if (window.innerWidth >= 1024) setFiltersOpen(true)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Collections stay eager because they also populate the normal filter panel.
  const { data: collectionsData } = useCollections()
  const { data: profile } = useProfile()
  const {
    state,
    loadMore,
    refresh,
    retry,
    checkpoint,
    updateView,
    restoreInstruction,
    acknowledgeRestore,
  } =
    useLibraryBrowseSession({
      query: rawQuery,
      enabled: profile !== undefined,
      userId: profile?.username,
    })
  const canManageDatasets = profile?.role === 'member' || profile?.role === 'admin'
  // Datasets are only ever read by the batch-action bar, so don't pay for the
  // request until that bar is actually on screen.
  const batchActionsVisible = selectMode && selectedIds.size > 0
  const { data: datasetsData } = useDatasets(canManageDatasets && batchActionsVisible)
  const { trigger: addDatasetMembers } = useAddDatasetMembers()

  // Derive sort from parsed filters (default 'added_at')
  const sortValue = parsed.sort ?? 'added_at'

  // Derive combined source filter for the dropdown (source + import_mode → "local:link")
  const combinedSource = parsed.source
    ? parsed.importMode
      ? `${parsed.source}:${parsed.importMode}`
      : parsed.source
    : ''

  const displayGalleries = useMemo<Gallery[]>(
    () => state.items.map(mapSearchItemToGallery),
    [state.items],
  )
  const total = state.total
  const error = state.error
  const isSessionLoading = state.status === 'loading'
  const itemElementsRef = useRef(new Map<number, HTMLElement>())
  const visibleStartRef = useRef(0)
  const layoutRef = useRef<BrowseLayoutSnapshot>({ columns: 4, width: 0, mode: viewMode })
  const pendingRestoreRef = useRef<{
    key: string
    identityKey: string
    index: number
    offset: number
  } | null>(null)
  const liveViewRef = useRef<{
    anchor: BrowseAnchor | null
    layout: BrowseLayoutSnapshot | null
  } | null>(null)
  const previousIdentityRef = useRef(state.identityKey)
  const handledRestoreKeyRef = useRef<string | null>(null)
  const scheduledRestoreKeyRef = useRef<string | null>(null)
  const [restoreRequest, setRestoreRequest] = useState<{
    key: string
    identityKey: string
    index: number
  }>()

  useEffect(() => {
    if (previousIdentityRef.current === state.identityKey) return
    previousIdentityRef.current = state.identityKey
    pendingRestoreRef.current = null
    liveViewRef.current = null
    setRestoreRequest(undefined)
  }, [state.identityKey])

  useEffect(() => {
    if (!restoreInstruction || restoreInstruction.identityKey !== state.identityKey) {
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
    const decision = decideAnchorRestore(anchor, displayGalleries, (gallery) => gallery.id)
    if (decision.kind === 'anchor') {
      const nextPending = {
        key: restoreInstruction.key,
        identityKey: state.identityKey,
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
        identityKey: state.identityKey,
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
      window.scrollTo(0, decision.kind === 'pixel' ? decision.scrollY : 0)
      handledRestoreKeyRef.current = restoreInstruction.key
      scheduledRestoreKeyRef.current = null
      acknowledgeRestore(restoreInstruction.key)
    })
    return () => {
      cancelAnimationFrame(frame)
      if (scheduledRestoreKeyRef.current === restoreInstruction.key)
        scheduledRestoreKeyRef.current = null
    }
  }, [acknowledgeRestore, displayGalleries, restoreInstruction, state.identityKey])

  const captureAnchor = useCallback(
    (preferred?: Gallery): BrowseAnchor => {
      const fallbackIndex = Math.min(
        visibleStartRef.current,
        Math.max(0, displayGalleries.length - 1),
      )
      const gallery = preferred ?? displayGalleries[fallbackIndex]
      const element = gallery ? itemElementsRef.current.get(gallery.id) : null
      return {
        itemId: gallery?.id ?? null,
        offset: element?.getBoundingClientRect().top ?? 0,
        scrollY: window.scrollY,
      }
    },
    [displayGalleries],
  )

  const openGallery = useCallback(
    (gallery: Gallery) => {
      checkpoint({ anchor: captureAnchor(gallery), layout: layoutRef.current })
      router.push(galleryHref(gallery.source, gallery.source_id))
    },
    [captureAnchor, checkpoint, router],
  )

  // `captureAnchor` is rebuilt whenever the gallery list changes, so the scroll
  // subscription below must not depend on it directly: an append that commits
  // before a scheduled capture frame fires would tear the effect down, cancel the
  // frame, and drop that scroll position without rescheduling it. Infinite scroll
  // makes that window routine, since scrolling is what triggers the append.
  const captureAnchorRef = useRef(captureAnchor)
  useLayoutEffect(() => {
    captureAnchorRef.current = captureAnchor
  }, [captureAnchor])

  useLayoutEffect(() => {
    let frame: number | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    const save = () => {
      const view = liveViewRef.current ?? {
        anchor: captureAnchorRef.current(),
        layout: layoutRef.current,
      }
      checkpoint(view)
    }
    const capture = () => {
      frame = undefined
      if (pendingRestoreRef.current) return
      const view = { anchor: captureAnchorRef.current(), layout: layoutRef.current }
      liveViewRef.current = view
      updateView(view)
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
  }, [checkpoint, updateView])

  const handleFavoriteToggle = useCallback(
    async (gallery: Gallery) => {
      try {
        await api.library.updateGallery(gallery.source, gallery.source_id, {
          favorited: !gallery.is_favorited,
        })
        toast.success(gallery.is_favorited ? t('library.unfavorited') : t('library.favorited'))
        await refresh()
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [refresh],
  )

  const handleDelete = useCallback(
    async (gallery: Gallery) => {
      if (!window.confirm(t('library.deleteConfirm', { title: gallery.title }))) return
      try {
        await api.library.deleteGallery(gallery.source, gallery.source_id)
        toast.success(t('library.deleted'))
        await refresh()
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [refresh],
  )

  const handleReadingListToggle = useCallback(
    async (g: Gallery) => {
      try {
        await api.library.updateGallery(g.source, g.source_id, {
          in_reading_list: !g.in_reading_list,
        })
        await refresh()
        toast.success(
          g.in_reading_list
            ? t('contextMenu.removeFromReadingList')
            : t('contextMenu.addToReadingList'),
        )
      } catch {
        toast.error(t('common.failedToLoad'))
      }
    },
    [refresh],
  )

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex, registerElement } = useGridKeyboard({
    totalItems: displayGalleries.length,
    colCount,
    onEnter: (i) => {
      const g = displayGalleries[i]
      if (g) openGallery(g)
    },
  })

  const handleRegisterElement = useCallback(
    (index: number, element: HTMLElement | null) => {
      registerElement(index, element)
      const gallery = displayGalleries[index]
      if (!gallery) return
      if (element) itemElementsRef.current.set(gallery.id, element)
      else itemElementsRef.current.delete(gallery.id)
    },
    [displayGalleries, registerElement],
  )

  const handleGridRestoreApplied = useCallback(
    (request: { key: string; index: number }) => {
      const pending = pendingRestoreRef.current
      if (
        !pending ||
        handledRestoreKeyRef.current === request.key ||
        pending.identityKey !== state.identityKey ||
        pending.key !== request.key ||
        pending.index !== request.index
      )
        return
      const gallery = displayGalleries[request.index]
      const element = gallery ? itemElementsRef.current.get(gallery.id) : null
      if (!element) return
      window.scrollTo(0, window.scrollY + element.getBoundingClientRect().top - pending.offset)
      pendingRestoreRef.current = null
      setRestoreRequest(undefined)
      handledRestoreKeyRef.current = pending.key
      acknowledgeRestore(pending.key)
    },
    [acknowledgeRestore, displayGalleries, state.identityKey],
  )

  const toggleSelectedId = useCallback(
    (id: number) => {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        if (next.has(id)) {
          next.delete(id)
        } else {
          next.add(id)
        }
        return next
      })
    },
    [setSelectedIds],
  )

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">{t('library.title')}</h1>

      {/* Filter Panel with collapsible toggle */}
      <div className="bg-vault-card border border-vault-border rounded-lg mb-6">
        {/* Toggle button — always visible */}
        <button
          onClick={() => setFiltersOpen((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-vault-text-secondary hover:text-vault-text transition-colors lg:cursor-default"
          aria-expanded={filtersOpen}
        >
          <span>{filtersOpen ? t('library.hideFilters') : t('library.showFilters')}</span>
          <ChevronDown
            size={16}
            className={`transition-transform duration-300 ${filtersOpen ? 'rotate-180' : 'rotate-0'}`}
          />
        </button>

        {/* Collapsible content — CSS transition via grid-rows */}
        <div
          className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
            filtersOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="overflow-hidden">
            <div className="px-4 pb-4 space-y-4 border-t border-vault-border pt-4">
              <div>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitSearch(inputValue)
                    }}
                    placeholder={t('library.searchPlaceholder')}
                    className="flex-1 bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
                  />
                  <button
                    onClick={() => setSyntaxHelpOpen((v) => !v)}
                    className="shrink-0 p-2 text-vault-text-muted hover:text-vault-accent transition-colors"
                    title={t('library.syntaxHelp')}
                  >
                    <HelpCircle size={16} />
                  </button>
                </div>
                {syntaxHelpOpen && (
                  <div className="mt-2 p-3 bg-vault-input border border-vault-border rounded-lg text-xs text-vault-text-secondary space-y-1 font-mono">
                    <p>character:rem — {t('library.syntaxTagSearch')}</p>
                    <p>rem — {t('library.syntaxNameOnly')}</p>
                    <p>-general:sketch — {t('library.syntaxExclude')}</p>
                    <p>title:&quot;re zero&quot; — {t('library.syntaxTitle')}</p>
                    <p>source:ehentai — {t('library.syntaxSource')}</p>
                    <p>rating:&gt;=4 — {t('library.syntaxRating')}</p>
                    <p>favorited:true — {t('library.syntaxFavorited')}</p>
                    <p>sort:rating — {t('library.syntaxSort')}</p>
                    <p>collection:5 — {t('library.syntaxCollection')}</p>
                    <p>artist_id:xxx — {t('library.syntaxArtistId')}</p>
                    <p>category:doujinshi — {t('library.syntaxCategory')}</p>
                    <p>import:link — {t('library.syntaxImportMode')}</p>
                    <p>rl:true — {t('library.syntaxReadingList')}</p>
                  </div>
                )}
              </div>

              {/* Additional Filters */}
              <div className="flex flex-wrap gap-4 items-center">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.minRating')}
                  </label>
                  <select
                    value={parsed.rating ?? ''}
                    onChange={(e) => {
                      setFilter('rating', e.target.value ? e.target.value : null)
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    <option value="">{t('library.any')}</option>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>
                        {n}+
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.source')}
                  </label>
                  <select
                    value={combinedSource}
                    onChange={(e) => {
                      const val = e.target.value
                      if (!val) {
                        setFilter('source', null)
                        setFilter('import', null)
                      } else {
                        const colonIdx = val.indexOf(':')
                        if (colonIdx !== -1) {
                          setFilter('source', val.slice(0, colonIdx))
                          setFilter('import', val.slice(colonIdx + 1))
                        } else {
                          setFilter('source', val)
                          setFilter('import', null)
                        }
                      }
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    <option value="">{t('library.allSources')}</option>
                    {(sourcesData ?? []).map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.value === 'local:link'
                          ? t('explorer.externalFolders')
                          : opt.value === 'local:copy'
                            ? t('explorer.jyzroxImport')
                            : opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                {categoriesData && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                      {t('library.filterCategory')}
                    </label>
                    <select
                      value={parsed.category ?? ''}
                      onChange={(e) => {
                        setFilter('category', e.target.value || null)
                      }}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                    >
                      <option value="">{t('library.allCategories')}</option>
                      <option value="__uncategorized__">
                        {t('library.categoryUncategorized')}
                      </option>
                      {categoriesData.categories.map((cat) => (
                        <option key={cat} value={cat}>
                          {cat}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {collectionsData && collectionsData.collections.length > 0 && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                      {t('collections.filterByCollection')}
                    </label>
                    <select
                      value={parsed.collection ?? ''}
                      onChange={(e) => setFilter('collection', e.target.value || null)}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                    >
                      <option value="">{t('collections.allCollections')}</option>
                      {collectionsData.collections.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} ({c.gallery_count})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.sort')}
                  </label>
                  <select
                    value={sortValue}
                    onChange={(e) => {
                      setFilter(
                        'sort',
                        e.target.value === 'added_at' ? null : e.target.value || null,
                      )
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    {SORT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label()}
                      </option>
                    ))}
                  </select>
                </div>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={parsed.favorited}
                    onChange={(e) => {
                      setFilter('favorited', e.target.checked ? 'true' : null)
                    }}
                    className="w-4 h-4 accent-yellow-500"
                  />
                  <span className="text-sm text-vault-text-secondary">
                    {t('library.favoritesOnly')}
                  </span>
                </label>

                <label className="flex items-center gap-2 text-sm text-vault-text-secondary cursor-pointer whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={parsed.readingList}
                    onChange={(e) => setFilter('rl', e.target.checked ? 'true' : null)}
                    className="rounded border-vault-border"
                  />
                  {t('library.readingListOnly')}
                </label>

                <button
                  onClick={() => {
                    setSelectMode(!selectMode)
                    setSelectedIds(new Set())
                  }}
                  className={`px-3 py-1 rounded text-sm font-medium border transition-colors ${
                    selectMode
                      ? 'bg-vault-accent/20 border-vault-accent text-vault-accent'
                      : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-vault-accent'
                  }`}
                >
                  {t('library.select')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {parsed.artistId && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs text-vault-text-muted uppercase tracking-wide">
            {t('library.artistFilter')}:
          </span>
          <span className="flex items-center gap-1 px-2 py-0.5 bg-vault-accent/10 border border-vault-accent/30 text-vault-accent rounded text-xs">
            {parsed.artistId}
            <button
              onClick={() => setFilter('artist_id', null)}
              className="ml-1 hover:text-red-400 transition-colors"
              aria-label={t('library.clearArtistFilter')}
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}

      {total !== null && (
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm text-vault-text-muted">
            {`${formatNumber(total)} ${t('library.galleries')}`}
          </span>
          {/* View mode toggle */}
          <div className="flex border border-vault-border rounded-lg overflow-hidden shrink-0">
            <button
              onClick={() => handleViewModeChange('grid')}
              title={t('browse.gridView')}
              className={`px-3 py-2 transition-colors ${viewMode === 'grid' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              onClick={() => handleViewModeChange('list')}
              title={t('browse.listView')}
              className={`px-3 py-2 transition-colors ${viewMode === 'list' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted hover:text-vault-text'}`}
            >
              <List size={15} />
            </button>
          </div>
        </div>
      )}

      {isSessionLoading && displayGalleries.length === 0 && <SkeletonGrid />}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400 flex items-center justify-between gap-3">
          <span>{error.message || t('common.failedToLoad')}</span>
          <button
            type="button"
            onClick={() => void retry()}
            className="shrink-0 rounded border border-red-400/40 px-3 py-1.5 text-sm hover:bg-red-500/10"
          >
            {t('common.retry')}
          </button>
        </div>
      )}

      {displayGalleries.length > 0 && (
        <VirtualGrid
          items={displayGalleries}
          getItemKey={(gallery) => gallery.id}
          columns={viewMode === 'list' ? { base: 1 } : gridColumns}
          gap={viewMode === 'list' ? 8 : getLibraryGridGap(displayPreferences.gallery_grid_density)}
          estimateHeight={viewMode === 'list' ? 150 : estimateLibraryGridRowHeight}
          measureRows={false}
          overscan={viewMode === 'list' ? 8 : 6}
          focusedIndex={focusedIndex}
          onColCountChange={setColCount}
          onRegisterElement={handleRegisterElement}
          onVisibleRangeChange={({ startIndex }) => {
            visibleStartRef.current = startIndex
          }}
          onLayoutChange={({ colCount: columns, containerWidth }) => {
            layoutRef.current = { columns, width: containerWidth, mode: viewMode }
          }}
          restoreRequest={
            restoreRequest?.identityKey === state.identityKey ? restoreRequest : undefined
          }
          onRestoreApplied={handleGridRestoreApplied}
          onLoadMore={state.status === 'error' ? undefined : loadMore}
          hasMore={state.hasMore}
          isLoading={isSessionLoading}
          renderItem={(gallery) => {
            const Card = viewMode === 'list' ? GalleryListCard : LibraryGalleryCard
            if (selectMode) {
              const isSelected = selectedIds.has(gallery.id)
              return (
                <div
                  onClick={() => {
                    toggleSelectedId(gallery.id)
                  }}
                  onContextMenu={(e) => e.preventDefault()}
                >
                  <Card
                    gallery={gallery}
                    thumbUrl={gallery.cover_thumb ?? undefined}
                    selected={isSelected}
                    selectMode={true}
                    onFavoriteToggle={handleFavoriteToggle}
                    onReadingListToggle={handleReadingListToggle}
                    onDelete={handleDelete}
                  />
                </div>
              )
            }
            return (
              <Card
                gallery={gallery}
                thumbUrl={gallery.cover_thumb ?? undefined}
                onClick={() => openGallery(gallery)}
                onFavoriteToggle={handleFavoriteToggle}
                onReadingListToggle={handleReadingListToggle}
                onDelete={handleDelete}
              />
            )
          }}
        />
      )}

      {!isSessionLoading && displayGalleries.length === 0 && !error && (
        <EmptyState icon={BookOpen} title={t('library.noGalleries')} />
      )}

      {selectMode && selectedIds.size > 0 && (
        <div className="fixed bottom-[calc(4rem+var(--sab))] lg:bottom-0 left-0 right-0 bg-vault-card border-t border-vault-border p-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between z-50">
          <div className="flex items-center gap-3">
            <span className="text-sm text-vault-text font-medium">
              {t('library.selectedCount', { count: String(selectedIds.size) })}
            </span>
            <button
              onClick={() => setSelectedIds(new Set(displayGalleries.map((g) => g.id)))}
              className="text-xs text-vault-accent hover:underline"
            >
              {t('library.selectAll')}
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="text-xs text-vault-text-muted hover:underline"
            >
              {t('library.deselectAll')}
            </button>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            <button
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'favorite',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-yellow-600 hover:bg-yellow-700 rounded text-white text-sm transition-colors"
            >
              {t('library.batchFavorite')}
            </button>
            <button
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'unfavorite',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors"
            >
              {t('library.batchUnfavorite')}
            </button>
            <button
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'add_to_reading_list',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                  setSelectedIds(new Set())
                  setSelectMode(false)
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm transition-colors flex items-center gap-1.5"
            >
              <Bookmark size={14} />
              {t('library.batchAddToReadingList')}
            </button>
            <button
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'remove_from_reading_list',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                  setSelectedIds(new Set())
                  setSelectMode(false)
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors flex items-center gap-1.5"
            >
              <BookmarkCheck size={14} />
              {t('library.batchRemoveFromReadingList')}
            </button>
            <select
              defaultValue=""
              onChange={async (e) => {
                const rating = Number(e.target.value)
                if (!rating && rating !== 0) return
                try {
                  const res = await api.library.batchGalleries({
                    action: 'rate',
                    gallery_ids: [...selectedIds],
                    rating,
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
                e.target.value = ''
              }}
              className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
            >
              <option value="" disabled>
                {t('library.batchRate')}
              </option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} ★
                </option>
              ))}
            </select>
            {collectionsData && collectionsData.collections.length > 0 && (
              <select
                defaultValue=""
                onChange={async (e) => {
                  const collectionId = Number(e.target.value)
                  if (!collectionId) return
                  try {
                    const res = await api.library.batchGalleries({
                      action: 'add_to_collection',
                      gallery_ids: [...selectedIds],
                      collection_id: collectionId,
                    })
                    toast.success(
                      t('collections.addedToCollection', { count: String(res.affected) }),
                    )
                    await refresh()
                    setSelectedIds(new Set())
                    setSelectMode(false)
                  } catch {
                    toast.error(t('collections.addFailed'))
                  }
                  e.target.value = ''
                }}
                className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
              >
                <option value="" disabled>
                  {t('collections.addToCollection')}
                </option>
                {collectionsData.collections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
            {datasetsData && datasetsData.datasets.length > 0 && (
              <select
                defaultValue=""
                onChange={async (event) => {
                  const datasetId = Number(event.target.value)
                  if (!datasetId) return
                  try {
                    const result = await addDatasetMembers({
                      id: datasetId,
                      selection: { gallery_ids: [...selectedIds] },
                    })
                    toast.success(t('datasets.membersAdded', { count: String(result.added) }))
                    setSelectedIds(new Set())
                    setSelectMode(false)
                  } catch {
                    toast.error(t('datasets.addFailed'))
                  }
                  event.target.value = ''
                }}
                className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
              >
                <option value="" disabled>
                  {t('datasets.addToDataset')}
                </option>
                {datasetsData.datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={() => {
                setBatchTagMode('add')
                setBatchTagList([])
                setBatchTagInput('')
              }}
              className="px-3 py-1.5 bg-green-600 hover:bg-green-700 rounded text-white text-sm transition-colors"
            >
              {t('library.batchAddTags')}
            </button>
            <button
              onClick={() => {
                setBatchTagMode('remove')
                setBatchTagList([])
                setBatchTagInput('')
              }}
              className="px-3 py-1.5 bg-orange-600 hover:bg-orange-700 rounded text-white text-sm transition-colors"
            >
              {t('library.batchRemoveTags')}
            </button>
            <button
              onClick={async () => {
                if (!confirm(t('library.batchDeleteConfirm', { count: String(selectedIds.size) })))
                  return
                try {
                  await api.library.batchGalleries({
                    action: 'delete',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('trash.movedToTrash'))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded text-white text-sm transition-colors"
            >
              {t('library.batchDelete')}
            </button>
            <button
              onClick={() => {
                setSelectMode(false)
                setSelectedIds(new Set())
              }}
              className="px-3 py-1.5 text-vault-text-muted hover:text-vault-text text-sm transition-colors"
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}

      {batchTagMode && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]"
          onClick={() => setBatchTagMode(null)}
        >
          <div
            className="bg-vault-card border border-vault-border rounded-lg p-4 w-96 max-w-[90vw]"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-medium text-vault-text mb-3">
              {batchTagMode === 'add' ? t('library.batchAddTags') : t('library.batchRemoveTags')}
            </h3>
            <div className="flex gap-2 mb-3">
              <input
                type="text"
                value={batchTagInput}
                onChange={(e) => setBatchTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && batchTagInput.trim()) {
                    setBatchTagList((prev) => [...prev, batchTagInput.trim()])
                    setBatchTagInput('')
                  }
                }}
                placeholder={t('library.batchTagsPlaceholder')}
                className="flex-1 bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted text-sm focus:outline-none focus:border-vault-border-hover"
                autoFocus
              />
            </div>
            <div className="flex flex-wrap gap-1 mb-3 min-h-[2rem]">
              {batchTagList.map((tag, i) => (
                <span
                  key={i}
                  className="flex items-center gap-1 px-2 py-0.5 bg-vault-accent/10 border border-vault-accent/30 text-vault-accent rounded text-xs"
                >
                  {tag}
                  <button
                    onClick={() => setBatchTagList((prev) => prev.filter((_, j) => j !== i))}
                    className="hover:text-red-400"
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setBatchTagMode(null)}
                className="px-3 py-1.5 text-vault-text-muted text-sm"
              >
                {t('common.cancel')}
              </button>
              <button
                disabled={batchTagList.length === 0}
                onClick={async () => {
                  try {
                    const res = await api.library.batchGalleries({
                      action: batchTagMode === 'add' ? 'add_tags' : 'remove_tags',
                      gallery_ids: [...selectedIds],
                      tags: batchTagList,
                    })
                    toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                    setBatchTagMode(null)
                    setBatchTagList([])
                    await refresh()
                  } catch {
                    toast.error(t('library.updateFailed'))
                  }
                }}
                className="px-3 py-1.5 bg-vault-accent hover:bg-vault-accent/80 rounded text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {t('library.batchTagsConfirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function LibraryPage() {
  return (
    <Suspense fallback={<SkeletonGrid />}>
      <LibraryContent />
    </Suspense>
  )
}
