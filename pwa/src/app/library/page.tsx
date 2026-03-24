'use client'

import { useState, useCallback, Suspense, useEffect, useMemo } from 'react'
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
import {
  useGalleryCategories,
  useLibrarySources,
  useSearchGalleries,
} from '@/hooks/useGalleries'
import type { Gallery } from '@/lib/types'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useScrollRestore } from '@/hooks/useScrollRestore'
import { useCollections } from '@/hooks/useCollections'
import { useUnifiedSearch } from '@/hooks/useUnifiedSearch'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { GalleryListCard } from '@/components/GalleryListCard'
import { SkeletonGrid } from '@/components/Skeleton'
import { EmptyState } from '@/components/EmptyState'
import { VirtualGrid } from '@/components/VirtualGrid'
import { t, formatNumber } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useSWRConfig } from 'swr'
import type { SearchGalleryItem } from '@/lib/api'

const SORT_OPTIONS = [
  { value: 'added_at', label: () => t('library.dateAdded') },
  { value: 'posted_at', label: () => t('library.datePosted') },
  { value: 'rating', label: () => t('library.rating') },
  { value: 'pages', label: () => t('library.pagesSort') },
  { value: 'title', label: () => t('library.titleSort') },
] as const

const PAGE_SIZE = 24

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
  const { mutate: globalMutate } = useSWRConfig()

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

  // Derive sort from parsed filters (default 'added_at')
  const sortValue = parsed.sort ?? 'added_at'

  // Derive combined source filter for the dropdown (source + import_mode → "local:link")
  const combinedSource = parsed.source
    ? parsed.importMode
      ? `${parsed.source}:${parsed.importMode}`
      : parsed.source
    : ''

  const { items: searchItems, total, isLoading, error, isReachingEnd, loadMore, mutate } =
    useSearchGalleries(rawQuery || ' ', { sort: sortValue, limit: PAGE_SIZE })

  const displayGalleries = useMemo<Gallery[]>(
    () => (searchItems ? searchItems.map(mapSearchItemToGallery) : []),
    [searchItems],
  )

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
          (key: unknown) => Array.isArray(key) && key[0] === 'search/galleries',
          undefined,
          { revalidate: true },
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
                      onChange={(e) =>
                        setFilter('collection', e.target.value || null)
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
                    value={sortValue}
                    onChange={(e) => {
                      setFilter('sort', e.target.value === 'added_at' ? null : e.target.value || null)
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
                    onChange={(e) =>
                      setFilter('rl', e.target.checked ? 'true' : null)
                    }
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

      {!isLoading && displayGalleries.length > 0 && (
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
          onLoadMore={loadMore}
          hasMore={!isReachingEnd}
          isLoading={isLoading}
        />
      )}

      {!isLoading && displayGalleries.length === 0 && !error && (
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
                setSelectedIds(new Set(displayGalleries.map((g) => g.id)))
              }
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
                  globalMutate(() => true)
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
