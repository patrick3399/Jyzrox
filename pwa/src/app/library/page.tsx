'use client'

import { useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { useLibraryGalleries } from '@/hooks/useGalleries'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { Pagination } from '@/components/Pagination'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { TagBadge } from '@/components/TagBadge'

const SORT_OPTIONS = [
  { value: 'added_at', label: 'Date Added' },
  { value: 'rating', label: 'Rating' },
  { value: 'pages', label: 'Pages' },
] as const

const SOURCE_OPTIONS = [
  { value: '', label: 'All Sources' },
  { value: 'ehentai', label: 'E-Hentai' },
  { value: 'pixiv', label: 'Pixiv' },
  { value: 'import', label: 'Import' },
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
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data, isLoading, error } = useLibraryGalleries({
    q: searchQuery || undefined,
    tags: includeTags.length > 0 ? includeTags : undefined,
    exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
    min_rating: minRating,
    favorited: onlyFavorited || undefined,
    source: source || undefined,
    sort,
    page,
    limit: PAGE_SIZE,
  })

  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(value)
      setPage(0)
    }, 400)
  }, [])

  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      setSearchQuery(searchInput)
      setPage(0)
    }
  }, [searchInput])

  const addIncludeTag = useCallback(() => {
    const tag = includeInput.trim()
    if (tag && !includeTags.includes(tag)) {
      setIncludeTags((prev) => [...prev, tag])
      setPage(0)
    }
    setIncludeInput('')
  }, [includeInput, includeTags])

  const addExcludeTag = useCallback(() => {
    const tag = excludeInput.trim()
    if (tag && !excludeTags.includes(tag)) {
      setExcludeTags((prev) => [...prev, tag])
      setPage(0)
    }
    setExcludeInput('')
  }, [excludeInput, excludeTags])

  const removeIncludeTag = useCallback((tag: string) => {
    setIncludeTags((prev) => prev.filter((t) => t !== tag))
    setPage(0)
  }, [])

  const removeExcludeTag = useCallback((tag: string) => {
    setExcludeTags((prev) => prev.filter((t) => t !== tag))
    setPage(0)
  }, [])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6 text-white">Library</h1>

        {/* Filters Panel */}
        <div className="bg-[#111111] border border-[#2a2a2a] rounded-lg p-4 mb-6 space-y-4">
          {/* Search */}
          <div className="flex gap-2">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search titles..."
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-[#444] text-sm"
            />
          </div>

          {/* Tag Filters */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Include Tags */}
            <div>
              <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
                Include Tags
              </label>
              <div className="flex gap-1 mb-2">
                <input
                  type="text"
                  value={includeInput}
                  onChange={(e) => setIncludeInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addIncludeTag()}
                  placeholder="character:rem"
                  className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                />
                <button
                  onClick={addIncludeTag}
                  className="px-2 py-1 bg-green-800 hover:bg-green-700 rounded text-white text-sm transition-colors"
                >
                  +
                </button>
              </div>
              <div className="flex flex-wrap gap-1">
                {includeTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => removeIncludeTag(tag)}
                    className="flex items-center gap-1 px-2 py-0.5 bg-green-900/40 border border-green-700/50 text-green-400 rounded text-xs hover:bg-red-900/40 hover:border-red-700/50 hover:text-red-400 transition-colors"
                  >
                    {tag}
                    <span className="text-xs">×</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Exclude Tags */}
            <div>
              <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
                Exclude Tags
              </label>
              <div className="flex gap-1 mb-2">
                <input
                  type="text"
                  value={excludeInput}
                  onChange={(e) => setExcludeInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addExcludeTag()}
                  placeholder="tag:value"
                  className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                />
                <button
                  onClick={addExcludeTag}
                  className="px-2 py-1 bg-red-800 hover:bg-red-700 rounded text-white text-sm transition-colors"
                >
                  -
                </button>
              </div>
              <div className="flex flex-wrap gap-1">
                {excludeTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => removeExcludeTag(tag)}
                    className="flex items-center gap-1 px-2 py-0.5 bg-red-900/40 border border-red-700/50 text-red-400 rounded text-xs hover:bg-green-900/40 hover:border-green-700/50 hover:text-green-400 transition-colors"
                  >
                    -{tag}
                    <span className="text-xs">×</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Additional Filters */}
          <div className="flex flex-wrap gap-4 items-center">
            {/* Min Rating */}
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 uppercase tracking-wide">Min Rating</label>
              <select
                value={minRating ?? ''}
                onChange={(e) => {
                  setMinRating(e.target.value ? Number(e.target.value) : undefined)
                  setPage(0)
                }}
                className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 text-white text-sm focus:outline-none"
              >
                <option value="">Any</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{n}+</option>
                ))}
              </select>
            </div>

            {/* Source */}
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 uppercase tracking-wide">Source</label>
              <select
                value={source}
                onChange={(e) => { setSource(e.target.value); setPage(0) }}
                className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 text-white text-sm focus:outline-none"
              >
                {SOURCE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            {/* Sort */}
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500 uppercase tracking-wide">Sort</label>
              <select
                value={sort}
                onChange={(e) => { setSort(e.target.value as typeof sort); setPage(0) }}
                className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 text-white text-sm focus:outline-none"
              >
                {SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            {/* Favorited Toggle */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={onlyFavorited}
                onChange={(e) => { setOnlyFavorited(e.target.checked); setPage(0) }}
                className="w-4 h-4 accent-yellow-500"
              />
              <span className="text-sm text-gray-400">Favorites only</span>
            </label>
          </div>
        </div>

        {/* Results Count */}
        {data && (
          <div className="text-sm text-gray-500 mb-4">
            {data.total.toLocaleString()} galleries
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="flex justify-center py-20">
            <LoadingSpinner />
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-4 text-red-400">
            {error.message || 'Failed to load library'}
          </div>
        )}

        {/* Gallery Grid */}
        {!isLoading && data && data.galleries.length > 0 && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {data.galleries.map((gallery) => (
                <Link key={gallery.id} href={`/library/${gallery.id}`}>
                  <LibraryGalleryCard gallery={gallery} />
                </Link>
              ))}
            </div>
            {totalPages > 1 && (
              <Pagination
                page={page}
                total={data.total}
                onChange={setPage}
              />
            )}
          </>
        )}

        {!isLoading && data && data.galleries.length === 0 && (
          <div className="text-center py-20 text-gray-500">
            No galleries found. Try adjusting your filters.
          </div>
        )}
      </div>
    </div>
  )
}
