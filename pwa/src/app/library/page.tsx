'use client'

import { useState, useCallback, Suspense, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import {
  BookOpen,
  Plus,
  Minus,
  X,
  ChevronDown,
  LayoutGrid,
  List,
  Bookmark,
  BookmarkCheck,
  HelpCircle,
} from 'lucide-react'
import {
  useInfiniteLibraryGalleries,
  useGalleryCategories,
  useLibrarySources,
  useSearchGalleries,
} from '@/hooks/useGalleries'
import type { Gallery } from '@/lib/types'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useScrollRestore } from '@/hooks/useScrollRestore'
import { useCollections } from '@/hooks/useCollections'
import { useLibraryFilters } from '@/hooks/useLibraryFilters'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { GalleryListCard } from '@/components/GalleryListCard'
import { SkeletonGrid } from '@/components/Skeleton'
import { EmptyState } from '@/components/EmptyState'
import { VirtualGrid } from '@/components/VirtualGrid'
import { t, formatNumber } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useSWRConfig } from 'swr'

const SORT_OPTIONS = [
  { value: 'added_at', label: () => t('library.dateAdded') },
  { value: 'rating', label: () => t('library.rating') },
  { value: 'pages', label: () => t('library.pagesSort') },
] as const

const PAGE_SIZE = 24

function isAdvancedQuery(q: string): boolean {
  if (!q) return false
  return (
    /(?:^|\s)(?:character|artist|parody|group|male|female|general|language|source|rating|favorited|title|sort):/.test(
      q,
    ) || /(?:^|\s)-\w+:/.test(q)
  )
}

function LibraryContent() {
  const router = useRouter()
  const { mutate: globalMutate } = useSWRConfig()
  const {
    state,
    dispatch,
    parsedSource,
    parsedImportMode,
    handleSearchChange,
    handleSearchCommit,
  } = useLibraryFilters()

  const {
    searchInput,
    searchQuery,
    includeTags,
    excludeTags,
    includeInput,
    excludeInput,
    minRating,
    onlyFavorited,
    inReadingList,
    sourceFilter,
    artistFilter,
    sort,
    collectionFilter,
    categoryFilter,
    selectMode,
    selectedIds,
  } = state

  const { data: categoriesData } = useGalleryCategories()
  const { data: sourcesData } = useLibrarySources()

  const [colCount, setColCount] = useState(4)
  const [batchTagMode, setBatchTagMode] = useState<'add' | 'remove' | null>(null)
  const [batchTagInput, setBatchTagInput] = useState('')
  const [batchTagList, setBatchTagList] = useState<string[]>([])
  const [syntaxHelpOpen, setSyntaxHelpOpen] = useState(false)

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

  const { data: collectionsData } = useCollections()

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        handleSearchCommit(searchInput)
      }
    },
    [searchInput, handleSearchCommit],
  )

  const addIncludeTag = useCallback(() => {
    dispatch({ type: 'ADD_INCLUDE_TAG', payload: includeInput })
  }, [dispatch, includeInput])

  const addExcludeTag = useCallback(() => {
    dispatch({ type: 'ADD_EXCLUDE_TAG', payload: excludeInput })
  }, [dispatch, excludeInput])

  const removeIncludeTag = useCallback(
    (tag: string) => dispatch({ type: 'REMOVE_INCLUDE_TAG', payload: tag }),
    [dispatch],
  )

  const removeExcludeTag = useCallback(
    (tag: string) => dispatch({ type: 'REMOVE_EXCLUDE_TAG', payload: tag }),
    [dispatch],
  )

  const { galleries, total, isLoading, error, isLoadingMore, isReachingEnd, loadMore, mutate } =
    useInfiniteLibraryGalleries({
      q: searchQuery || undefined,
      tags: includeTags.length > 0 ? includeTags : undefined,
      exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
      min_rating: minRating,
      favorited: onlyFavorited || undefined,
      in_reading_list: inReadingList || undefined,
      source: parsedSource,
      import_mode: parsedImportMode,
      artist: artistFilter || undefined,
      sort,
      limit: PAGE_SIZE,
      collection: collectionFilter,
      category: categoryFilter || undefined,
    })

  // Advanced search: detect tag syntax in committed search query
  const advancedSearch = isAdvancedQuery(searchQuery)
  const {
    items: searchItems,
    isLoading: searchLoading,
    isReachingEnd: searchEnd,
    loadMore: searchLoadMore,
    total: searchTotal,
  } = useSearchGalleries(advancedSearch ? searchQuery || '' : '', { sort, limit: PAGE_SIZE })

  const searchGalleries: Gallery[] = useMemo(() => {
    if (!advancedSearch || !searchItems) return []
    return searchItems.map((item) => ({
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
      is_favorited: item.favorited,
      my_rating: null,
      uploader: item.uploader ?? '',
      artist_id: null,
      download_status: item.download_status as Gallery['download_status'],
      added_at: item.added_at ?? '',
      posted_at: item.posted_at,
      tags_array: item.tags,
      cover_thumb: null,
      in_reading_list: false,
      source_url: null,
      import_mode: null,
    }))
  }, [advancedSearch, searchItems])

  const displayGalleries = advancedSearch ? searchGalleries : galleries
  const displayTotal = advancedSearch ? searchTotal : total
  const displayLoading = advancedSearch ? searchLoading : isLoading
  const displayLoadMore = advancedSearch ? searchLoadMore : loadMore
  const displayReachingEnd = advancedSearch ? searchEnd : isReachingEnd
  const displayLoadingMore = advancedSearch ? searchLoading : isLoadingMore

  const handleFavoriteToggle = useCallback(
    async (gallery: Gallery) => {
      try {
        await api.library.updateGallery(gallery.source, gallery.source_id, {
          favorited: !gallery.is_favorited,
        })
        toast.success(gallery.is_favorited ? t('library.unfavorited') : t('library.favorited'))
        mutate()
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [mutate],
  )

  const handleDelete = useCallback(
    async (gallery: Gallery) => {
      if (!window.confirm(t('library.deleteConfirm', { title: gallery.title }))) return
      try {
        await api.library.deleteGallery(gallery.source, gallery.source_id)
        toast.success(t('library.deleted'))
        mutate()
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [mutate],
  )

  const handleReadingListToggle = useCallback(
    async (g: Gallery) => {
      try {
        await api.library.updateGallery(g.source, g.source_id, {
          in_reading_list: !g.in_reading_list,
        })
        globalMutate(
          (key: unknown) => typeof key === 'string' && key.startsWith('library-galleries'),
        )
        toast.success(
          g.in_reading_list
            ? t('contextMenu.removeFromReadingList')
            : t('contextMenu.addToReadingList'),
        )
      } catch {
        toast.error(t('common.failedToLoad'))
      }
    },
    [globalMutate],
  )

  // ── Scroll restoration ──────────────────────────────────
  const { saveScroll } = useScrollRestore('library_scrollY', displayGalleries.length > 0)

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex, registerElement } = useGridKeyboard({
    totalItems: displayGalleries.length,
    colCount,
    onEnter: (i) => {
      const g = displayGalleries[i]
      if (g) {
        saveScroll()
        router.push(`/library/${g.source}/${g.source_id}`)
      }
    },
  })

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
                    value={searchInput}
                    onChange={(e) => handleSearchChange(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
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
                {advancedSearch && searchQuery && (
                  <p className="text-xs text-vault-accent mt-1">
                    {t('library.advancedSearchActive')}
                  </p>
                )}
                {syntaxHelpOpen && (
                  <div className="mt-2 p-3 bg-vault-input border border-vault-border rounded-lg text-xs text-vault-text-secondary space-y-1 font-mono">
                    <p>character:rem — {t('library.syntaxTagSearch')}</p>
                    <p>-general:sketch — {t('library.syntaxExclude')}</p>
                    <p>title:&quot;re zero&quot; — {t('library.syntaxTitle')}</p>
                    <p>source:ehentai — {t('library.syntaxSource')}</p>
                    <p>rating:&gt;=4 — {t('library.syntaxRating')}</p>
                    <p>favorited:true — {t('library.syntaxFavorited')}</p>
                    <p>sort:rating — {t('library.syntaxSort')}</p>
                  </div>
                )}
              </div>

              {/* Tag Filters */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-vault-text-muted uppercase tracking-wide mb-1">
                    {t('library.includeTags')}
                  </label>
                  <div className="flex gap-1 mb-2">
                    <input
                      type="text"
                      value={includeInput}
                      onChange={(e) =>
                        dispatch({ type: 'SET_INCLUDE_INPUT', payload: e.target.value })
                      }
                      onKeyDown={(e) => e.key === 'Enter' && addIncludeTag()}
                      placeholder={t('library.tagFilterPlaceholder')}
                      className="flex-1 bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
                    />
                    <button
                      onClick={addIncludeTag}
                      className="p-1.5 bg-green-600 hover:bg-green-700 rounded text-white transition-colors"
                    >
                      <Plus size={14} />
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {includeTags.map((tag) => (
                      <button
                        key={tag}
                        onClick={() => removeIncludeTag(tag)}
                        className="flex items-center gap-1 px-2 py-0.5 bg-green-500/10 border border-green-500/30 text-green-400 rounded text-xs hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-400 transition-colors"
                      >
                        {tag} <span className="text-xs">×</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-vault-text-muted uppercase tracking-wide mb-1">
                    {t('library.excludeTags')}
                  </label>
                  <div className="flex gap-1 mb-2">
                    <input
                      type="text"
                      value={excludeInput}
                      onChange={(e) =>
                        dispatch({ type: 'SET_EXCLUDE_INPUT', payload: e.target.value })
                      }
                      onKeyDown={(e) => e.key === 'Enter' && addExcludeTag()}
                      placeholder={t('library.excludeTagPlaceholder')}
                      className="flex-1 bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
                    />
                    <button
                      onClick={addExcludeTag}
                      className="p-1.5 bg-red-600 hover:bg-red-700 rounded text-white transition-colors"
                    >
                      <Minus size={14} />
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {excludeTags.map((tag) => (
                      <button
                        key={tag}
                        onClick={() => removeExcludeTag(tag)}
                        className="flex items-center gap-1 px-2 py-0.5 bg-red-500/10 border border-red-500/30 text-red-400 rounded text-xs hover:bg-green-500/10 hover:border-green-500/30 hover:text-green-400 transition-colors"
                      >
                        -{tag} <span className="text-xs">×</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Additional Filters */}
              <div className="flex flex-wrap gap-4 items-center">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.minRating')}
                  </label>
                  <select
                    value={minRating ?? ''}
                    onChange={(e) => {
                      dispatch({
                        type: 'SET_MIN_RATING',
                        payload: e.target.value ? Number(e.target.value) : undefined,
                      })
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
                    value={sourceFilter}
                    onChange={(e) => {
                      dispatch({ type: 'SET_SOURCE_FILTER', payload: e.target.value })
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    <option value="">{t('library.allSources')}</option>
                    {(sourcesData ?? []).map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.value === 'local:link'
                          ? t('library.monitored')
                          : opt.value === 'local:copy'
                            ? t('library.imported')
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
                      value={categoryFilter}
                      onChange={(e) => {
                        dispatch({ type: 'SET_CATEGORY', payload: e.target.value })
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
                      value={collectionFilter ?? ''}
                      onChange={(e) =>
                        dispatch({
                          type: 'SET_COLLECTION_FILTER',
                          payload: e.target.value ? Number(e.target.value) : undefined,
                        })
                      }
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
                    value={sort}
                    onChange={(e) => {
                      dispatch({ type: 'SET_SORT', payload: e.target.value as typeof sort })
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
                    checked={onlyFavorited}
                    onChange={(e) => {
                      dispatch({ type: 'SET_ONLY_FAVORITED', payload: e.target.checked })
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
                    checked={inReadingList}
                    onChange={(e) =>
                      dispatch({ type: 'SET_IN_READING_LIST', payload: e.target.checked })
                    }
                    className="rounded border-vault-border"
                  />
                  {t('library.readingListOnly')}
                </label>

                <button
                  onClick={() => {
                    dispatch({ type: 'SET_SELECT_MODE', payload: !selectMode })
                    dispatch({ type: 'SET_SELECTED_IDS', payload: new Set() })
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

      {artistFilter && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs text-vault-text-muted uppercase tracking-wide">
            {t('library.artistFilter')}:
          </span>
          <span className="flex items-center gap-1 px-2 py-0.5 bg-vault-accent/10 border border-vault-accent/30 text-vault-accent rounded text-xs">
            {artistFilter}
            <button
              onClick={() => dispatch({ type: 'SET_ARTIST_FILTER', payload: '' })}
              className="ml-1 hover:text-red-400 transition-colors"
              aria-label={t('library.clearArtistFilter')}
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}

      {displayTotal !== undefined && (
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm text-vault-text-muted">
            {`${formatNumber(displayTotal)} ${t('library.galleries')}`}
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

      {displayLoading && <SkeletonGrid />}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400">
          {error.message || t('common.failedToLoad')}
        </div>
      )}

      {!displayLoading && displayGalleries.length > 0 && (
        <VirtualGrid
          items={displayGalleries}
          columns={
            viewMode === 'list' ? { base: 1 } : { base: 4, sm: 5, md: 6, lg: 8, xl: 10, xxl: 12 }
          }
          gap={viewMode === 'list' ? 8 : 12}
          estimateHeight={viewMode === 'list' ? 134 : 300}
          focusedIndex={focusedIndex}
          onColCountChange={setColCount}
          onRegisterElement={registerElement}
          renderItem={(gallery) => {
            const Card = viewMode === 'list' ? GalleryListCard : LibraryGalleryCard
            if (selectMode) {
              const isSelected = selectedIds.has(gallery.id)
              return (
                <div
                  onClick={() => {
                    dispatch({ type: 'TOGGLE_SELECTED_ID', payload: gallery.id })
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
                onClick={() => {
                  saveScroll()
                  router.push(`/library/${gallery.source}/${gallery.source_id}`)
                }}
                onFavoriteToggle={handleFavoriteToggle}
                onReadingListToggle={handleReadingListToggle}
                onDelete={handleDelete}
              />
            )
          }}
          onLoadMore={displayLoadMore}
          hasMore={!displayReachingEnd}
          isLoading={displayLoadingMore}
        />
      )}

      {!displayLoading && displayGalleries.length === 0 && !error && (
        <EmptyState icon={BookOpen} title={t('library.noGalleries')} />
      )}

      {selectMode && selectedIds.size > 0 && (
        <div className="fixed bottom-[calc(4rem+var(--sab))] lg:bottom-0 left-0 right-0 bg-vault-card border-t border-vault-border p-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between z-50">
          <div className="flex items-center gap-3">
            <span className="text-sm text-vault-text font-medium">
              {t('library.selectedCount', { count: String(selectedIds.size) })}
            </span>
            <button
              onClick={() =>
                dispatch({
                  type: 'SET_SELECTED_IDS',
                  payload: new Set(displayGalleries.map((g) => g.id)),
                })
              }
              className="text-xs text-vault-accent hover:underline"
            >
              {t('library.selectAll')}
            </button>
            <button
              onClick={() => dispatch({ type: 'SET_SELECTED_IDS', payload: new Set() })}
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
                  globalMutate(() => true)
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
                  globalMutate(() => true)
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
                  globalMutate(() => true)
                  dispatch({ type: 'CLEAR_SELECTION' })
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
                  globalMutate(() => true)
                  dispatch({ type: 'CLEAR_SELECTION' })
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
                  globalMutate(() => true)
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
                    dispatch({ type: 'CLEAR_SELECTION' })
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
                  const res = await api.library.batchGalleries({
                    action: 'delete',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('trash.movedToTrash'))
                  globalMutate(() => true)
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded text-white text-sm transition-colors"
            >
              {t('library.batchDelete')}
            </button>
            <button
              onClick={() => dispatch({ type: 'CLEAR_SELECTION' })}
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
                    globalMutate(() => true)
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
