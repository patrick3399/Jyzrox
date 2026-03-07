'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { useEhSearch } from '@/hooks/useGalleries'
import { api } from '@/lib/api'
import { EhGalleryCard } from '@/components/GalleryCard'
import { Pagination } from '@/components/Pagination'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AlertBanner } from '@/components/AlertBanner'
import { TagBadge } from '@/components/TagBadge'
import { RatingStars } from '@/components/RatingStars'
import type { EhGallery } from '@/lib/types'

const CATEGORIES = [
  { value: 'doujinshi', label: 'Doujinshi' },
  { value: 'manga', label: 'Manga' },
  { value: 'artist_cg', label: 'Artist CG' },
  { value: 'game_cg', label: 'Game CG' },
  { value: 'image_set', label: 'Image Set' },
  { value: 'cosplay', label: 'Cosplay' },
  { value: 'western', label: 'Western' },
  { value: 'misc', label: 'Misc' },
]

export default function BrowsePage() {
  const [inputValue, setInputValue] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [selectedGallery, setSelectedGallery] = useState<EhGallery | null>(null)
  const [downloadUrl, setDownloadUrl] = useState('')
  const [downloadSource, setDownloadSource] = useState('ehentai')
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const searchParams = {
    q: searchQuery || undefined,
    category: category || undefined,
    page,
  }

  const { data, isLoading, error } = useEhSearch(searchParams)

  // Debounced search
  const handleInputChange = useCallback((value: string) => {
    setInputValue(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(value)
      setPage(0)
    }, 500)
  }, [])

  const handleSearchSubmit = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setSearchQuery(inputValue)
    setPage(0)
  }, [inputValue])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearchSubmit()
  }, [handleSearchSubmit])

  const handleCategoryChange = useCallback((cat: string | null) => {
    setCategory(cat)
    setPage(0)
  }, [])

  const handleDownloadUrl = useCallback(async () => {
    if (!downloadUrl.trim()) return
    setDownloadStatus(null)
    setDownloadError(null)
    try {
      const result = await api.download.enqueue(downloadUrl.trim(), downloadSource)
      setDownloadStatus(`Queued: job ${result.job_id}`)
      setDownloadUrl('')
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'Failed to enqueue download')
    }
  }, [downloadUrl, downloadSource])

  const handleDownloadGallery = useCallback(async (gallery: EhGallery) => {
    const url = `https://e-hentai.org/g/${gallery.gid}/${gallery.token}/`
    setDownloadStatus(null)
    setDownloadError(null)
    try {
      const result = await api.download.enqueue(url, 'ehentai')
      setDownloadStatus(`Queued: job ${result.job_id}`)
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'Failed to enqueue download')
    }
  }, [])

  const totalPages = data ? Math.ceil(data.total / 25) : 0

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <h1 className="text-2xl font-bold mb-6 text-white">Browse E-Hentai</h1>

        {/* Search Bar */}
        <div className="bg-[#111111] border border-[#2a2a2a] rounded-lg p-4 mb-4">
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search galleries..."
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-[#444]"
            />
            <button
              onClick={handleSearchSubmit}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white font-medium transition-colors"
            >
              Search
            </button>
          </div>

          {/* Category Filter */}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => handleCategoryChange(null)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                category === null
                  ? 'bg-blue-600 text-white'
                  : 'bg-[#1a1a1a] border border-[#2a2a2a] text-gray-400 hover:text-white'
              }`}
            >
              All
            </button>
            {CATEGORIES.map((cat) => (
              <button
                key={cat.value}
                onClick={() => handleCategoryChange(cat.value)}
                className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                  category === cat.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-[#1a1a1a] border border-[#2a2a2a] text-gray-400 hover:text-white'
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>

        {/* Alerts */}
        {downloadStatus && (
          <AlertBanner alerts={[downloadStatus]} onDismiss={() => setDownloadStatus(null)} />
        )}
        {downloadError && (
          <AlertBanner alerts={[downloadError]} onDismiss={() => setDownloadError(null)} />
        )}

        {/* Results */}
        {isLoading && (
          <div className="flex justify-center py-20">
            <LoadingSpinner />
          </div>
        )}

        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-4 text-red-400">
            {error.message || 'Failed to load search results'}
          </div>
        )}

        {!isLoading && data && (
          <>
            <div className="text-sm text-gray-500 mb-4">
              {data.total.toLocaleString()} results
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              {data.galleries.map((gallery) => (
                <EhGalleryCard
                  key={`${gallery.gid}-${gallery.token}`}
                  gallery={gallery}
                  onClick={() => setSelectedGallery(gallery)}
                />
              ))}
            </div>
            {totalPages > 1 && (
              <Pagination
                page={page}
                total={data.total}
                onChange={(p: number) => { setPage(p) }}
              />
            )}
          </>
        )}

        {!isLoading && !error && !data && (
          <div className="text-center py-20 text-gray-500">
            Enter a search query to browse E-Hentai galleries.
          </div>
        )}

        {/* Quick Download Bar */}
        <div className="mt-8 bg-[#111111] border border-[#2a2a2a] rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Quick Download by URL
          </h2>
          <div className="flex gap-2">
            <input
              type="text"
              value={downloadUrl}
              onChange={(e) => setDownloadUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDownloadUrl()}
              placeholder="https://e-hentai.org/g/..."
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-[#444] text-sm"
            />
            <select
              value={downloadSource}
              onChange={(e) => setDownloadSource(e.target.value)}
              className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-2 text-white text-sm focus:outline-none"
            >
              <option value="ehentai">E-Hentai</option>
              <option value="pixiv">Pixiv</option>
            </select>
            <button
              onClick={handleDownloadUrl}
              className="px-4 py-2 bg-green-700 hover:bg-green-600 rounded text-white text-sm font-medium transition-colors"
            >
              Download
            </button>
          </div>
        </div>
      </div>

      {/* Gallery Modal */}
      {selectedGallery && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={() => setSelectedGallery(null)}
        >
          <div
            className="bg-[#111111] border border-[#2a2a2a] rounded-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex gap-4 p-5">
              {/* Thumbnail */}
              <div className="flex-shrink-0">
                {selectedGallery.thumb ? (
                  <img
                    src={selectedGallery.thumb}
                    alt={selectedGallery.title}
                    className="w-32 h-44 object-cover rounded"
                  />
                ) : (
                  <div className="w-32 h-44 bg-[#1a1a1a] rounded flex items-center justify-center text-gray-600 text-xs">
                    No Image
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-white leading-snug mb-1">
                  {selectedGallery.title}
                </h2>
                {selectedGallery.title_jpn && (
                  <p className="text-sm text-gray-400 mb-2">{selectedGallery.title_jpn}</p>
                )}
                <div className="flex flex-wrap gap-2 text-xs text-gray-400 mb-3">
                  <span className="bg-[#1a1a1a] border border-[#2a2a2a] px-2 py-0.5 rounded">
                    {selectedGallery.category}
                  </span>
                  <span>{selectedGallery.pages} pages</span>
                  <span>{new Date(selectedGallery.posted_at * 1000).toLocaleDateString()}</span>
                </div>
                <div className="mb-3">
                  <RatingStars rating={selectedGallery.rating} readonly />
                </div>

                {/* Tags */}
                <div className="flex flex-wrap gap-1 max-h-32 overflow-y-auto mb-4">
                  {selectedGallery.tags.map((tag) => (
                    <TagBadge key={tag} tag={tag} />
                  ))}
                </div>

                {/* Actions */}
                <div className="flex gap-2">
                  <button
                    onClick={() => handleDownloadGallery(selectedGallery)}
                    className="px-4 py-2 bg-green-700 hover:bg-green-600 rounded text-white text-sm font-medium transition-colors"
                  >
                    Download
                  </button>
                  <button
                    onClick={() => setSelectedGallery(null)}
                    className="px-4 py-2 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#444] rounded text-gray-400 text-sm transition-colors"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
