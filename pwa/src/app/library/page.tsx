'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import Link from 'next/link'
import { BookOpen, Plus, Minus } from 'lucide-react'
import { useLibraryGalleries } from '@/hooks/useGalleries'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { Pagination } from '@/components/Pagination'
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
  { value: 'import', label: () => 'Import' },
]

const PAGE_SIZE = 24

export default function LibraryPage() {
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [includeTags, setIncludeTags] = useState<string[]>([])
  const [excludeTags, setExcludeTags] = useState<string[]>([])
  const [includeInput, setIncludeInput] = useState('')
  const [excludeInput, setExcludeInput] = useState('')
  const [minRating, setMinRating] = useState<number | undefined>(undefined)
  const [onlyFavorited, setOnlyFavorited] = useState(false)
  const [source, setSource] = useState('')
  const [sort, setSort] = useState<'added_at' | 'rating' | 'pages'>('added_at')
  const [page, setPage] = useState(0)
  // cursor-based pagination state
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  // stack of cursors for navigating backwards; each entry is the cursor that
  // was active when we moved forward (undefined = first page)
  const [cursorHistory, setCursorHistory] = useState<(string | undefined)[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // Reset all pagination state whenever filters change
  const resetPagination = useCallback(() => {
    setPage(0)
    setCursor(undefined)
    setCursorHistory([])
  }, [])

  const { data, isLoading, error } = useLibraryGalleries({
    q: searchQuery || undefined,
    tags: includeTags.length > 0 ? includeTags : undefined,
    exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
    min_rating: minRating,
    favorited: onlyFavorited || undefined,
    source: source || undefined,
    sort,
    // When a cursor is active, send it instead of the page number so the
    // backend uses keyset pagination. Otherwise fall back to page-based.
    ...(cursor ? { cursor } : { page }),
    limit: PAGE_SIZE,
  })

  // Derived: are we in cursor mode (backend returned next_cursor)?
  const isCursorMode = data !== undefined && data.next_cursor !== undefined
  const hasNext = isCursorMode ? (data?.has_next ?? false) : false
  const hasPrev = cursorHistory.length > 0

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchInput(value)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        setSearchQuery(value)
        resetPagination()
      }, 400)
    },
    [resetPagination],
  )

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        setSearchQuery(searchInput)
        resetPagination()
      }
    },
    [searchInput, resetPagination],
  )

  const addIncludeTag = useCallback(() => {
    const tag = includeInput.trim()
    if (tag && !includeTags.includes(tag)) {
      setIncludeTags((prev) => [...prev, tag])
      resetPagination()
    }
    setIncludeInput('')
  }, [includeInput, includeTags, resetPagination])

  const addExcludeTag = useCallback(() => {
    const tag = excludeInput.trim()
    if (tag && !excludeTags.includes(tag)) {
      setExcludeTags((prev) => [...prev, tag])
      resetPagination()
    }
    setExcludeInput('')
  }, [excludeInput, excludeTags, resetPagination])

  const removeIncludeTag = useCallback(
    (tag: string) => {
      setIncludeTags((prev) => prev.filter((t) => t !== tag))
      resetPagination()
    },
    [resetPagination],
  )

  const removeExcludeTag = useCallback(
    (tag: string) => {
      setExcludeTags((prev) => prev.filter((t) => t !== tag))
      resetPagination()
    },
    [resetPagination],
  )

  // Page-based: total is known → show numbered pagination
  const totalPages = data?.total !== undefined ? Math.ceil(data.total / PAGE_SIZE) : 0

  const handleNextCursor = useCallback(() => {
    if (!data?.next_cursor) return
    setCursorHistory((prev) => [...prev, cursor])
    setCursor(data.next_cursor ?? undefined)
  }, [data, cursor])

  const handlePrevCursor = useCallback(() => {
    if (cursorHistory.length === 0) return
    const prev = [...cursorHistory]
    const restored = prev.pop()
    setCursorHistory(prev)
    setCursor(restored)
  }, [cursorHistory])

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
                  placeholder="character:rem"
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
                  placeholder="tag:value"
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
                  resetPagination()
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
                value={source}
                onChange={(e) => {
                  setSource(e.target.value)
                  resetPagination()
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
                  resetPagination()
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
                  resetPagination()
                }}
                className="w-4 h-4 accent-yellow-500"
              />
              <span className="text-sm text-vault-text-secondary">
                {t('library.favoritesOnly')}
              </span>
            </label>
          </div>
        </div>

        {data && (
          <div className="text-sm text-vault-text-muted mb-4">
            {data.total !== undefined
              ? `${data.total.toLocaleString()} ${t('library.galleries')}`
              : `${data.galleries.length} ${t('library.galleries')}`}
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

        {!isLoading && data && data.galleries.length > 0 && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {data.galleries.map((gallery) => (
                <Link key={gallery.id} href={`/library/${gallery.id}`}>
                  <LibraryGalleryCard gallery={gallery} />
                </Link>
              ))}
            </div>

            {/* Cursor-based pagination: shown when backend returns next_cursor */}
            {isCursorMode && (hasPrev || hasNext) && (
              <div className="flex items-center justify-center gap-3 py-4">
                <button
                  type="button"
                  onClick={handlePrevCursor}
                  disabled={!hasPrev}
                  className="flex items-center gap-1 px-4 py-2 rounded-lg bg-vault-card border border-vault-border hover:border-vault-accent hover:text-vault-text text-vault-text-secondary text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label="Previous page"
                >
                  ← {t('tags.prev')}
                </button>
                <button
                  type="button"
                  onClick={handleNextCursor}
                  disabled={!hasNext}
                  className="flex items-center gap-1 px-4 py-2 rounded-lg bg-vault-card border border-vault-border hover:border-vault-accent hover:text-vault-text text-vault-text-secondary text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label="Next page"
                >
                  {t('tags.next')} →
                </button>
              </div>
            )}

            {/* Page-based pagination: shown when backend returns total */}
            {!isCursorMode && totalPages > 1 && data.total !== undefined && (
              <Pagination page={page} total={data.total} pageSize={PAGE_SIZE} onChange={setPage} />
            )}
          </>
        )}

        {!isLoading && data && data.galleries.length === 0 && (
          <EmptyState icon={BookOpen} title={t('library.noGalleries')} />
        )}
      </div>
    </div>
  )
}
