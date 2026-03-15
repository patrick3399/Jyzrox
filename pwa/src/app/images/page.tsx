'use client'

import { Suspense, useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useImageBrowser } from '@/hooks/useImageBrowser'
import { useThumbhash } from '@/hooks/useThumbhash'
import { JustifiedGrid } from '@/components/JustifiedGrid'
import { t } from '@/lib/i18n'
import type { BrowseImage } from '@/lib/types'

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

  const tags = useMemo(() => tagsParam ? tagsParam.split(',').filter(Boolean) : [], [tagsParam])
  const excludeTags = useMemo(() => excludeParam ? excludeParam.split(',').filter(Boolean) : [], [excludeParam])

  const [tagInput, setTagInput] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)

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

  const { images, isLoading, isLoadingMore, isReachingEnd, loadMore } = useImageBrowser({
    tags: tags.length > 0 ? tags : undefined,
    exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
    limit: 60,
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

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">{t('images.title')}</h1>

      {/* Tag filter bar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
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
            targetRowHeight={240}
            boxSpacing={4}
            renderItem={renderItem}
            onLoadMore={loadMore}
            hasMore={!isReachingEnd}
            isLoading={isLoading || isLoadingMore}
          />
        )}
      </div>

      {!isLoading && images.length === 0 && (
        <div className="text-center text-vault-text-secondary py-12">
          {t('images.noResults')}
        </div>
      )}
    </div>
  )
}
