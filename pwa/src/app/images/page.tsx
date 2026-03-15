'use client'

import { Suspense, useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useImageBrowser } from '@/hooks/useImageBrowser'
import { useTimeRange, useTimelinePercentiles } from '@/hooks/useTimeRange'
import { useLibrarySources, useGalleryCategories } from '@/hooks/useGalleries'
import { useThumbhash } from '@/hooks/useThumbhash'
import { JustifiedGrid } from '@/components/JustifiedGrid'
import { TimelineScrubber } from '@/components/TimelineScrubber'
import { t } from '@/lib/i18n'
import type { BrowseImage } from '@/lib/types'

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

export default function ImageBrowserPage() {
  return (
    <Suspense>
      <ImageBrowserInner />
    </Suspense>
  )
}

function ImageBrowserInner() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const tagsParam = searchParams.get('tags')
  const excludeParam = searchParams.get('exclude_tags')

  const sourceParam = searchParams.get('source') ?? ''
  const categoryParam = searchParams.get('category') ?? ''

  const tags = useMemo(() => tagsParam ? tagsParam.split(',').filter(Boolean) : [], [tagsParam])
  const excludeTags = useMemo(() => excludeParam ? excludeParam.split(',').filter(Boolean) : [], [excludeParam])

  const [sourceFilter, setSourceFilter] = useState(sourceParam)
  const [categoryFilter, setCategoryFilter] = useState(categoryParam)
  const [tagInput, setTagInput] = useState('')
  const [jumpAt, setJumpAt] = useState<string | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w) setContainerWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const targetRowHeight = useMemo(() => {
    if (containerWidth < 768) return 150
    if (containerWidth < 1024) return 180
    return 200
  }, [containerWidth])

  const { data: dynamicSources } = useLibrarySources()
  const { data: categoriesData } = useGalleryCategories()

  // Sync source and category filters to URL
  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString())
    if (sourceFilter) params.set('source', sourceFilter)
    else params.delete('source')
    if (categoryFilter) params.set('category', categoryFilter)
    else params.delete('category')
    const qs = params.toString()
    const newUrl = qs ? `/images?${qs}` : '/images'
    router.replace(newUrl, { scroll: false })
  }, [sourceFilter, categoryFilter, searchParams, router])

  // Reset jumpAt when filters change
  useEffect(() => {
    setJumpAt(undefined)
  }, [sourceFilter, categoryFilter, tags, excludeTags])

  const filterParams = useMemo(() => ({
    tags: tags.length > 0 ? tags : undefined,
    exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
    source: sourceFilter || undefined,
    category: categoryFilter || undefined,
  }), [tags, excludeTags, sourceFilter, categoryFilter])

  const { minAt, maxAt } = useTimeRange(filterParams)
  const { percentiles } = useTimelinePercentiles(filterParams)

  const { images, isLoading, isLoadingMore, isReachingEnd, loadMore } = useImageBrowser({
    ...filterParams,
    limit: 60,
    jumpAt,
  })

  const uniqueHashes = useMemo(() => {
    const seen = new Set<string>()
    for (const img of images) {
      if (img.thumbhash) seen.add(img.thumbhash)
    }
    return Array.from(seen)
  }, [images])

  const thumbhashUrls = useThumbhash(uniqueHashes)

  const getAspectRatio = useCallback((img: BrowseImage) => {
    if (img.width && img.height && img.height > 0) return img.width / img.height
    return 0.7 // default portrait ratio
  }, [])

  const handleAddTag = useCallback(() => {
    const tag = tagInput.trim()
    if (!tag || tags.includes(tag)) return
    const newTags = [...tags, tag]
    const params = new URLSearchParams(searchParams.toString())
    params.set('tags', newTags.join(','))
    router.replace(`/images?${params.toString()}`)
    setTagInput('')
  }, [tagInput, tags, searchParams, router])

  const handleRemoveTag = useCallback((tag: string) => {
    const newTags = tags.filter((tg) => tg !== tag)
    const params = new URLSearchParams(searchParams.toString())
    if (newTags.length > 0) {
      params.set('tags', newTags.join(','))
    } else {
      params.delete('tags')
    }
    router.replace(`/images?${params.toString()}`)
  }, [tags, searchParams, router])

  const handleImageClick = useCallback((img: BrowseImage) => {
    if (img.source && img.source_id) {
      router.push(`/reader/${encodeURIComponent(img.source)}/${encodeURIComponent(img.source_id)}?page=${img.page_num}`)
    }
  }, [router])

  const handleTimelineJump = useCallback((timestamp: string) => {
    setJumpAt(timestamp)
    scrollRef.current?.scrollTo({ top: 0, behavior: 'instant' })
  }, [])

  const renderItem = useCallback((img: BrowseImage, geometry: { width: number; height: number }) => {
    const thumbhashUrl = thumbhashUrls.get(img.thumbhash || '') || null

    return (
      <button
        onClick={() => handleImageClick(img)}
        className="block w-full h-full overflow-hidden rounded-sm relative group cursor-pointer"
      >
        {/* Thumbhash placeholder */}
        {thumbhashUrl && (
          <img
            src={thumbhashUrl}
            alt=""
            className="absolute inset-0 w-full h-full object-cover"
            aria-hidden
          />
        )}
        {/* Actual image */}
        <img
          src={img.thumb_path || ''}
          alt=""
          loading="lazy"
          className="absolute inset-0 w-full h-full object-cover transition-opacity duration-300"
          onLoad={(e) => {
            e.currentTarget.style.opacity = '1'
          }}
          style={{ opacity: img.thumbhash ? 0 : undefined }}
        />
        {/* Hover overlay */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors" />
      </button>
    )
  }, [handleImageClick, thumbhashUrls])

  // Suppress the native viewport scrollbar: lock html/body overflow so the
  // only scroll surface is our wrapper div (which hides its own scrollbar).
  useEffect(() => {
    setScrollEl(scrollRef.current)
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    return () => {
      document.documentElement.style.overflow = ''
      document.body.style.overflow = ''
    }
  }, [])

  return (
    /*
     * Scroll wrapper strategy:
     * - Fixed to the viewport, offset left on desktop to clear the sidebar.
     * - Bottom offset clears the mobile bottom tab bar.
     * - `overflow-y: scroll` + `scrollbar-width: none` (via .hide-scrollbar)
     *   reliably hides the scrollbar on macOS Chrome "Always show scrollbars"
     *   because the scroll context is an element, not the viewport.
     * - html/body are locked to overflow: hidden so no duplicate scrollbar
     *   appears on the viewport itself.
     */
    <div
      ref={scrollRef}
      className="hide-scrollbar fixed inset-0 lg:left-56 bottom-[calc(4rem+var(--sab))] lg:bottom-0 bg-vault-bg text-vault-text"
    >
      <div className="px-4 lg:px-6 xl:px-8 py-6 pt-[calc(1.5rem+var(--sat)/2)] lg:pt-6">
        <h1 className="text-2xl font-bold mb-4">{t('images.title')}</h1>

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <div className="flex items-center gap-2">
            <label className="text-xs text-vault-text-muted uppercase tracking-wide">
              {t('library.source')}
            </label>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="bg-vault-input border border-vault-border rounded px-2 py-1.5 text-vault-text text-sm focus:outline-none"
            >
              <option value="">{t('library.allSources')}</option>
              {(dynamicSources ?? []).map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {sourceDisplayName(opt.value)}
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
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="bg-vault-input border border-vault-border rounded px-2 py-1.5 text-vault-text text-sm focus:outline-none"
              >
                <option value="">{t('library.allCategories')}</option>
                <option value="__uncategorized__">{t('library.categoryUncategorized')}</option>
                {categoriesData.categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAddTag() }}
              placeholder={t('images.filterByTags')}
              className="bg-vault-input border border-vault-border rounded px-3 py-1.5 text-sm text-vault-text placeholder:text-vault-text-secondary focus:outline-none focus:border-vault-accent"
            />
            <button
              onClick={handleAddTag}
              className="bg-vault-accent text-white rounded px-3 py-1.5 text-sm hover:bg-vault-accent/90 transition-colors"
            >
              {t('common.add')}
            </button>
          </div>
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 bg-vault-accent/10 text-vault-accent rounded-full px-3 py-1 text-xs"
            >
              {tag}
              <button
                onClick={() => handleRemoveTag(tag)}
                className="hover:text-red-400 transition-colors ml-1"
              >
                ×
              </button>
            </span>
          ))}
        </div>

        {/* Grid */}
        <div ref={containerRef}>
          {containerWidth > 0 && (
            <JustifiedGrid
              items={images}
              getAspectRatio={getAspectRatio}
              containerWidth={containerWidth}
              targetRowHeight={targetRowHeight}
              boxSpacing={4}
              renderItem={renderItem}
              onLoadMore={loadMore}
              hasMore={!isReachingEnd}
              isLoading={isLoading || isLoadingMore}
              scrollElement={scrollEl}
            />
          )}
        </div>

        {!isLoading && images.length === 0 && (
          <div className="text-center text-vault-text-secondary py-12">
            {t('images.noResults')}
          </div>
        )}
      </div>

      <TimelineScrubber
        minAt={minAt}
        maxAt={maxAt}
        enabled={images.length > 0}
        onJump={handleTimelineJump}
        images={images}
        scrollElement={scrollEl}
        percentiles={percentiles}
      />
    </div>
  )
}
