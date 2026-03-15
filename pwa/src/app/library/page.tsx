'use client'

import { useState, useCallback, Suspense, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { BookOpen, Plus, Minus, X, ChevronDown, LayoutGrid, List } from 'lucide-react'
import { useInfiniteLibraryGalleries } from '@/hooks/useGalleries'
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

const SORT_OPTIONS = [
  { value: 'added_at', label: () => t('library.dateAdded') },
  { value: 'rating', label: () => t('library.rating') },
  { value: 'pages', label: () => t('library.pagesSort') },
] as const

const SOURCE_OPTIONS = [
  { value: '', label: () => t('library.allSources') },
  { value: 'ehentai', label: () => 'E-Hentai' },
  { value: 'pixiv', label: () => 'Pixiv' },
  { value: 'local:link', label: () => t('library.monitored') },
  { value: 'local:copy', label: () => t('library.imported') },
]

const PAGE_SIZE = 24

function LibraryContent() {
  const router = useRouter()
  const { state, dispatch, parsedSource, parsedImportMode, handleSearchChange, handleSearchCommit } =
    useLibraryFilters()

  const {
    searchInput,
    searchQuery,
    includeTags,
    excludeTags,
    includeInput,
    excludeInput,
    minRating,
    onlyFavorited,
    sourceFilter,
    artistFilter,
    sort,
    collectionFilter,
    selectMode,
    selectedIds,
  } = state

  const [colCount, setColCount] = useState(4)

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

  const { galleries, total, isLoading, error, isLoadingMore, isReachingEnd, loadMore } =
    useInfiniteLibraryGalleries({
      q: searchQuery || undefined,
      tags: includeTags.length > 0 ? includeTags : undefined,
      exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
      min_rating: minRating,
      favorited: onlyFavorited || undefined,
      source: parsedSource,
      import_mode: parsedImportMode,
      artist: artistFilter || undefined,
      sort,
      limit: PAGE_SIZE,
      collection: collectionFilter,
    })

  // ── Scroll restoration ──────────────────────────────────
  const { saveScroll } = useScrollRestore('library_scrollY', galleries.length > 0)

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex, registerElement } = useGridKeyboard({
    totalItems: galleries.length,
    colCount,
    onEnter: (i) => {
      const g = galleries[i]
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
              <input
                type="text"
                value={searchInput}
                onChange={(e) => handleSearchChange(e.target.value)}
                onKeyDown={handleSearchKeyDown}
                placeholder={t('library.searchPlaceholder')}
                className="w-full bg-vault-input border border-vault-border rounded-lg px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-border-hover text-sm"
              />

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
                      onChange={(e) => dispatch({ type: 'SET_INCLUDE_INPUT', payload: e.target.value })}
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
                      onChange={(e) => dispatch({ type: 'SET_EXCLUDE_INPUT', payload: e.target.value })}
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
                    {SOURCE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label()}
                      </option>
                    ))}
                  </select>
                </div>

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
                  <span className="text-sm text-vault-text-secondary">{t('library.favoritesOnly')}</span>
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

      {total !== undefined && (
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

      {isLoading && <SkeletonGrid />}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400">
          {error.message || t('common.failedToLoad')}
        </div>
      )}

      {!isLoading && galleries.length > 0 && (
        <VirtualGrid
          items={galleries}
          columns={viewMode === 'list' ? { base: 1 } : { base: 4, sm: 5, md: 6, lg: 8, xl: 10, xxl: 12 }}
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
                >
                  <Card
                    gallery={gallery}
                    thumbUrl={gallery.cover_thumb ?? undefined}
                    selected={isSelected}
                    selectMode={true}
                  />
                </div>
              )
            }
            return (
              <Link href={`/library/${gallery.source}/${gallery.source_id}`} onClick={() => saveScroll()}>
                <Card gallery={gallery} thumbUrl={gallery.cover_thumb ?? undefined} />
              </Link>
            )
          }}
          onLoadMore={loadMore}
          hasMore={!isReachingEnd}
          isLoading={isLoadingMore}
        />
      )}

      {!isLoading && galleries.length === 0 && !error && (
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
                dispatch({ type: 'SET_SELECTED_IDS', payload: new Set(galleries.map((g) => g.id)) })
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
                  setTimeout(() => window.location.reload(), 500)
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
                  setTimeout(() => window.location.reload(), 500)
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
              className="px-3 py-1.5 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors"
            >
              {t('library.batchUnfavorite')}
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
                  setTimeout(() => window.location.reload(), 500)
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
                    toast.success(t('collections.addedToCollection', { count: String(res.affected) }))
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
              onClick={async () => {
                if (!confirm(t('library.batchDeleteConfirm', { count: String(selectedIds.size) }))) return
                try {
                  const res = await api.library.batchGalleries({
                    action: 'delete',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchDeleteSuccess', { count: String(res.affected) }))
                  setTimeout(() => window.location.reload(), 500)
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
