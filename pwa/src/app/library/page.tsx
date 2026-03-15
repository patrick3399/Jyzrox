'use client'

import { useState, useCallback, useRef, useEffect, Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams, useRouter } from 'next/navigation'
import { BookOpen, Plus, Minus, X } from 'lucide-react'
import { useInfiniteLibraryGalleries, useLibrarySources } from '@/hooks/useGalleries'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useScrollRestore } from '@/hooks/useScrollRestore'
import { useCollections } from '@/hooks/useCollections'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { LoadingSpinner } from '@/components/LoadingSpinner'
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

function sourceDisplayName(value: string): string {
  const STATIC: Record<string, string> = {
    ehentai: 'E-Hentai',
    pixiv: 'Pixiv',
    local: 'Local',
    gallery_dl: 'gallery-dl',
  }
  if (value === 'local:link') return t('library.monitored')
  if (value === 'local:copy') return t('library.imported')
  return STATIC[value] ?? value
}

const PAGE_SIZE = 24

function LibraryContent() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const [searchInput, setSearchInput] = useState(searchParams.get('q') ?? '')
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') ?? '')
  const [includeTags, setIncludeTags] = useState<string[]>(
    searchParams.get('tags')?.split(',').filter(Boolean) ?? []
  )
  const [excludeTags, setExcludeTags] = useState<string[]>(
    searchParams.get('notags')?.split(',').filter(Boolean) ?? []
  )
  const [includeInput, setIncludeInput] = useState('')
  const [excludeInput, setExcludeInput] = useState('')
  const [minRating, setMinRating] = useState<number | undefined>(
    searchParams.get('rating') ? Number(searchParams.get('rating')) : undefined,
  )
  const [onlyFavorited, setOnlyFavorited] = useState(searchParams.get('fav') === '1')
  const [sourceFilter, setSourceFilter] = useState(searchParams.get('source') ?? '')
  const [artistFilter, setArtistFilter] = useState(searchParams.get('artist') ?? '')
  const [sort, setSort] = useState<'added_at' | 'rating' | 'pages'>(
    (searchParams.get('sort') as 'added_at' | 'rating' | 'pages') ?? 'added_at',
  )
  const [collectionFilter, setCollectionFilter] = useState<number | undefined>(undefined)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [colCount, setColCount] = useState(4)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data: collectionsData } = useCollections()
  const { data: dynamicSources } = useLibrarySources()

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // Sync active filters back to URL so browser back restores state
  useEffect(() => {
    const params = new URLSearchParams()
    if (searchQuery) params.set('q', searchQuery)
    if (sourceFilter) params.set('source', sourceFilter)
    if (sort !== 'added_at') params.set('sort', sort)
    if (minRating !== undefined) params.set('rating', String(minRating))
    if (onlyFavorited) params.set('fav', '1')
    if (artistFilter) params.set('artist', artistFilter)
    if (includeTags.length > 0) params.set('tags', includeTags.join(','))
    if (excludeTags.length > 0) params.set('notags', excludeTags.join(','))

    const qs = params.toString()
    const newUrl = qs ? `/library?${qs}` : '/library'
    router.replace(newUrl, { scroll: false })
  }, [searchQuery, sourceFilter, sort, minRating, onlyFavorited, artistFilter, includeTags, excludeTags, router])

  // Split compound source filter values like "local:link" → source="local", import_mode="link"
  const [parsedSource, parsedImportMode] = (() => {
    if (!sourceFilter) return [undefined, undefined]
    const colonIdx = sourceFilter.indexOf(':')
    if (colonIdx === -1) return [sourceFilter, undefined]
    return [sourceFilter.slice(0, colonIdx), sourceFilter.slice(colonIdx + 1)]
  })()

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

  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(value)
    }, 400)
  }, [])

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        setSearchQuery(searchInput)
      }
    },
    [searchInput],
  )

  const addIncludeTag = useCallback(() => {
    const tag = includeInput.trim()
    if (tag && !includeTags.includes(tag)) {
      setIncludeTags((prev) => [...prev, tag])
    }
    setIncludeInput('')
  }, [includeInput, includeTags])

  const addExcludeTag = useCallback(() => {
    const tag = excludeInput.trim()
    if (tag && !excludeTags.includes(tag)) {
      setExcludeTags((prev) => [...prev, tag])
    }
    setExcludeInput('')
  }, [excludeInput, excludeTags])

  const removeIncludeTag = useCallback((tag: string) => {
    setIncludeTags((prev) => prev.filter((t) => t !== tag))
  }, [])

  const removeExcludeTag = useCallback((tag: string) => {
    setExcludeTags((prev) => prev.filter((t) => t !== tag))
  }, [])

  // ── Scroll restoration ──────────────────────────────────
  const { saveScroll } = useScrollRestore('library_scrollY', galleries.length > 0)

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex } = useGridKeyboard({
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

        {/* Filters Panel */}
        <div className="bg-vault-card border border-vault-border rounded-lg p-4 mb-6 space-y-4">
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
                  onChange={(e) => setIncludeInput(e.target.value)}
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
                  onChange={(e) => setExcludeInput(e.target.value)}
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
                  setMinRating(e.target.value ? Number(e.target.value) : undefined)
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
                  setSourceFilter(e.target.value)
                }}
                className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
              >
                <option value="">{t('library.allSources')}</option>
                {(dynamicSources ?? []).map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {sourceDisplayName(opt.value)}
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
                  onChange={(e) => setCollectionFilter(e.target.value ? Number(e.target.value) : undefined)}
                  className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                >
                  <option value="">{t('collections.allCollections')}</option>
                  {collectionsData.collections.map(c => (
                    <option key={c.id} value={c.id}>{c.name} ({c.gallery_count})</option>
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
                  setSort(e.target.value as typeof sort)
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
                  setOnlyFavorited(e.target.checked)
                }}
                className="w-4 h-4 accent-yellow-500"
              />
              <span className="text-sm text-vault-text-secondary">
                {t('library.favoritesOnly')}
              </span>
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

        {artistFilter && (
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs text-vault-text-muted uppercase tracking-wide">
              {t('library.artistFilter')}:
            </span>
            <span className="flex items-center gap-1 px-2 py-0.5 bg-vault-accent/10 border border-vault-accent/30 text-vault-accent rounded text-xs">
              {artistFilter}
              <button
                onClick={() => setArtistFilter('')}
                className="ml-1 hover:text-red-400 transition-colors"
                aria-label={t('library.clearArtistFilter')}
              >
                <X size={12} />
              </button>
            </span>
          </div>
        )}

        {total !== undefined && (
          <div className="text-sm text-vault-text-muted mb-4">
            {`${formatNumber(total)} ${t('library.galleries')}`}
          </div>
        )}

        {isLoading && (
          <div className="flex justify-center py-20">
            <LoadingSpinner />
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400">
            {error.message || t('common.failedToLoad')}
          </div>
        )}

        {!isLoading && galleries.length > 0 && (
          <VirtualGrid
            items={galleries}
            columns={{ base: 4, sm: 5, md: 6, lg: 8, xl: 10, xxl: 12 }}
            gap={12}
            estimateHeight={300}
            focusedIndex={focusedIndex}
            onColCountChange={setColCount}
            renderItem={(gallery) => {
              if (selectMode) {
                const isSelected = selectedIds.has(gallery.id)
                return (
                  <div
                    onClick={() => {
                      setSelectedIds((prev) => {
                        const next = new Set(prev)
                        if (next.has(gallery.id)) next.delete(gallery.id)
                        else next.add(gallery.id)
                        return next
                      })
                    }}
                  >
                    <LibraryGalleryCard
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
                  <LibraryGalleryCard
                    gallery={gallery}
                    thumbUrl={gallery.cover_thumb ?? undefined}
                  />
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
                onClick={() => setSelectedIds(new Set(galleries.map((g) => g.id)))}
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
                    const res = await api.library.batchGalleries({ action: 'favorite', gallery_ids: [...selectedIds] })
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
                    const res = await api.library.batchGalleries({ action: 'unfavorite', gallery_ids: [...selectedIds] })
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
                    const res = await api.library.batchGalleries({ action: 'rate', gallery_ids: [...selectedIds], rating })
                    toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                    setTimeout(() => window.location.reload(), 500)
                  } catch {
                    toast.error(t('library.updateFailed'))
                  }
                  e.target.value = ''
                }}
                className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
              >
                <option value="" disabled>{t('library.batchRate')}</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{n} ★</option>
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
                      setSelectedIds(new Set())
                      setSelectMode(false)
                    } catch {
                      toast.error(t('collections.addFailed'))
                    }
                    e.target.value = ''
                  }}
                  className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
                >
                  <option value="" disabled>{t('collections.addToCollection')}</option>
                  {collectionsData.collections.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              )}
              <button
                onClick={async () => {
                  if (!confirm(t('library.batchDeleteConfirm', { count: String(selectedIds.size) }))) return
                  try {
                    const res = await api.library.batchGalleries({ action: 'delete', gallery_ids: [...selectedIds] })
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
                onClick={() => { setSelectMode(false); setSelectedIds(new Set()) }}
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
    <Suspense fallback={<div className="flex justify-center py-20"><LoadingSpinner /></div>}>
      <LibraryContent />
    </Suspense>
  )
}
