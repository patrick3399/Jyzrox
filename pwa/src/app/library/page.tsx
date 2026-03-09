'use client'

import { useState, useCallback, useRef, useEffect, Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams, useRouter } from 'next/navigation'
import { BookOpen, Plus, Minus } from 'lucide-react'
import { useInfiniteLibraryGalleries } from '@/hooks/useGalleries'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { t } from '@/lib/i18n'

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
  const searchParams = useSearchParams()
  const router = useRouter()

  const [searchInput, setSearchInput] = useState(searchParams.get('q') ?? '')
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') ?? '')
  const [includeTags, setIncludeTags] = useState<string[]>([])
  const [excludeTags, setExcludeTags] = useState<string[]>([])
  const [includeInput, setIncludeInput] = useState('')
  const [excludeInput, setExcludeInput] = useState('')
  const [minRating, setMinRating] = useState<number | undefined>(
    searchParams.get('rating') ? Number(searchParams.get('rating')) : undefined,
  )
  const [onlyFavorited, setOnlyFavorited] = useState(searchParams.get('fav') === '1')
  const [sourceFilter, setSourceFilter] = useState(searchParams.get('source') ?? '')
  const [sort, setSort] = useState<'added_at' | 'rating' | 'pages'>(
    (searchParams.get('sort') as 'added_at' | 'rating' | 'pages') ?? 'added_at',
  )
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)

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

    const qs = params.toString()
    const newUrl = qs ? `/library?${qs}` : '/library'
    router.replace(newUrl, { scroll: false })
  }, [searchQuery, sourceFilter, sort, minRating, onlyFavorited, router])

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
      sort,
      limit: PAGE_SIZE,
    })

  // Intersection Observer: auto-trigger loadMore when sentinel enters viewport
  useEffect(() => {
    if (!sentinelRef.current) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !isLoadingMore && !isReachingEnd) {
          loadMore()
        }
      },
      { rootMargin: '200px' },
    )
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [isLoadingMore, isReachingEnd, loadMore])

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

  return (
    <div className="min-h-screen">
      <div className="max-w-7xl mx-auto px-4 py-6">
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
                {SOURCE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label()}
                  </option>
                ))}
              </select>
            </div>

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
          </div>
        </div>

        {total !== undefined && (
          <div className="text-sm text-vault-text-muted mb-4">
            {`${total.toLocaleString()} ${t('library.galleries')}`}
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
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {galleries.map((gallery) => (
                <Link key={gallery.id} href={`/library/${gallery.id}`}>
                  <LibraryGalleryCard
                    gallery={gallery}
                    thumbUrl={gallery.cover_thumb ?? undefined}
                  />
                </Link>
              ))}
            </div>

            {/* Infinite scroll sentinel */}
            {!isReachingEnd && (
              <div ref={sentinelRef} className="flex justify-center py-8">
                {isLoadingMore ? (
                  <LoadingSpinner />
                ) : (
                  <button
                    onClick={loadMore}
                    className="px-6 py-2 bg-vault-card border border-vault-border rounded-lg text-vault-text-secondary text-sm hover:border-vault-accent transition-colors"
                  >
                    {t('common.loadMore')}
                  </button>
                )}
              </div>
            )}
          </>
        )}

        {!isLoading && galleries.length === 0 && !error && (
          <EmptyState icon={BookOpen} title={t('library.noGalleries')} />
        )}
      </div>
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
