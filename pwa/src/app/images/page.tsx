'use client'

import { Suspense, useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useImageBrowser } from '@/hooks/useImageBrowser'
import { useTimeRange, useTimelinePercentiles } from '@/hooks/useTimeRange'
import { useLibrarySources, useGalleryCategories } from '@/hooks/useGalleries'
import { useThumbhash } from '@/hooks/useThumbhash'
import { useLongPress } from '@/hooks/useLongPress'
import { JustifiedGrid } from '@/components/JustifiedGrid'
import { TimelineScrubber } from '@/components/TimelineScrubber'
import { ImageContextMenu } from '@/components/Reader/ImageContextMenu'
import { SauceNaoModal } from '@/components/SauceNaoModal'
import { t } from '@/lib/i18n'
import { api } from '@/lib/api'
import { toast } from 'sonner'
import { Heart } from 'lucide-react'
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

  const tags = useMemo(() => (tagsParam ? tagsParam.split(',').filter(Boolean) : []), [tagsParam])
  const excludeTags = useMemo(
    () => (excludeParam ? excludeParam.split(',').filter(Boolean) : []),
    [excludeParam],
  )

  const [sourceFilter, setSourceFilter] = useState(sourceParam)
  const [categoryFilter, setCategoryFilter] = useState(categoryParam)
  const [favoritedFilter, setFavoritedFilter] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [jumpAt, setJumpAt] = useState<string | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null)

  // Context menu state
  const [imageMenu, setImageMenu] = useState<{
    open: boolean
    position: { x: number; y: number }
    imageUrl: string
    imageName: string
    imageId: number
    pageNum: number
    source: string
    sourceId: string
  } | null>(null)

  // SauceNAO modal state
  const [saucenaoImageId, setSaucenaoImageId] = useState<number | null>(null)

  const activeImageRef = useRef<BrowseImage | null>(null)

  // Optimistic favorite overrides
  const [localFavOverrides, setLocalFavOverrides] = useState<Map<number, boolean>>(new Map())

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
  }, [sourceFilter, categoryFilter, tags, excludeTags, favoritedFilter])

  const filterParams = useMemo(
    () => ({
      tags: tags.length > 0 ? tags : undefined,
      exclude_tags: excludeTags.length > 0 ? excludeTags : undefined,
      source: sourceFilter || undefined,
      category: categoryFilter || undefined,
      favorited: favoritedFilter || undefined,
    }),
    [tags, excludeTags, sourceFilter, categoryFilter, favoritedFilter],
  )

  const { minAt, maxAt } = useTimeRange(filterParams)
  const { percentiles } = useTimelinePercentiles(filterParams)

  const { images, favoritedImageIds, mutate, isLoading, isLoadingMore, isReachingEnd, loadMore } =
    useImageBrowser({
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

  const handleRemoveTag = useCallback(
    (tag: string) => {
      const newTags = tags.filter((tg) => tg !== tag)
      const params = new URLSearchParams(searchParams.toString())
      if (newTags.length > 0) {
        params.set('tags', newTags.join(','))
      } else {
        params.delete('tags')
      }
      router.replace(`/images?${params.toString()}`)
    },
    [tags, searchParams, router],
  )

  const handleImageClick = useCallback(
    (img: BrowseImage) => {
      if (img.source && img.source_id) {
        router.push(
          `/reader/${encodeURIComponent(img.source)}/${encodeURIComponent(img.source_id)}?page=${img.page_num}`,
        )
      }
    },
    [router],
  )

  const handleTimelineJump = useCallback((timestamp: string) => {
    setJumpAt(timestamp)
    scrollRef.current?.scrollTo({ top: 0, behavior: 'instant' })
  }, [])

  const isFavorited = useCallback(
    (imageId: number) => {
      if (localFavOverrides.has(imageId)) return localFavOverrides.get(imageId)!
      return favoritedImageIds.has(imageId)
    },
    [localFavOverrides, favoritedImageIds],
  )

  const handleLongPress = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    const img = activeImageRef.current
    if (!img) return
    const pos =
      'touches' in e
        ? {
            x: (e as React.TouchEvent).touches[0].clientX,
            y: (e as React.TouchEvent).touches[0].clientY,
          }
        : { x: (e as React.MouseEvent).clientX, y: (e as React.MouseEvent).clientY }
    setImageMenu({
      open: true,
      position: pos,
      imageUrl: img.file_path || img.thumb_path || '',
      imageName: `page_${img.page_num}`,
      imageId: img.id,
      pageNum: img.page_num,
      source: img.source || '',
      sourceId: img.source_id || '',
    })
  }, [])

  const {
    onTouchStart: lpStart,
    onTouchMove: lpMove,
    onTouchEnd: lpEnd,
    onContextMenu: lpMenu,
  } = useLongPress({ onLongPress: handleLongPress })

  const handleToggleFavorite = useCallback(async () => {
    if (!imageMenu) return
    const { imageId } = imageMenu
    const wasFavorited = isFavorited(imageId)

    setImageMenu(null)

    // Optimistic update
    setLocalFavOverrides((prev) => new Map(prev).set(imageId, !wasFavorited))

    try {
      if (wasFavorited) {
        await api.library.unfavoriteImage(imageId)
      } else {
        await api.library.favoriteImage(imageId)
      }
      toast.success(wasFavorited ? t('reader.imageUnfavorited') : t('reader.imageFavorited'))
      mutate(
        (prev) => {
          if (!prev) return prev
          return prev.map((page) => ({
            ...page,
            favorited_image_ids: wasFavorited
              ? page.favorited_image_ids.filter((id) => id !== imageId)
              : [...page.favorited_image_ids, imageId],
          }))
        },
        { revalidate: false },
      )
      setLocalFavOverrides((prev) => {
        const next = new Map(prev)
        next.delete(imageId)
        return next
      })
    } catch {
      // Revert
      setLocalFavOverrides((prev) => {
        const next = new Map(prev)
        next.delete(imageId)
        return next
      })
      toast.error(t('reader.favoriteFailed'))
    }
  }, [imageMenu, isFavorited, mutate])

  const handleViewGallery = useCallback(() => {
    if (!imageMenu) return
    const { source, sourceId } = imageMenu
    if (source && sourceId) {
      router.push(`/library/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`)
    }
    setImageMenu(null)
  }, [imageMenu, router])

  const handleHideImage = useCallback(async () => {
    if (!imageMenu) return
    const { source, sourceId, pageNum } = imageMenu

    setImageMenu(null)

    if (!window.confirm(t('reader.hideImageConfirm'))) return

    try {
      await api.library.deleteImage(source, sourceId, pageNum)
      toast.success(t('reader.imageHidden'))
      await mutate()
    } catch {
      toast.error(t('common.error'))
    }
  }, [imageMenu, mutate])

  const renderItem = useCallback(
    (img: BrowseImage, geometry: { width: number; height: number }) => {
      const thumbhashUrl = thumbhashUrls.get(img.thumbhash || '') || null
      const favorited = isFavorited(img.id)
      const isSelected = imageMenu?.imageId === img.id

      return (
        <button
          onClick={() => handleImageClick(img)}
          onTouchStart={(e) => {
            activeImageRef.current = img
            lpStart(e)
          }}
          onTouchMove={lpMove}
          onTouchEnd={lpEnd}
          onContextMenu={(e) => {
            activeImageRef.current = img
            lpMenu(e)
          }}
          className="block w-full h-full overflow-hidden rounded-sm relative group cursor-pointer select-none [&_img]:pointer-events-none"
          style={{ WebkitTouchCallout: 'none' }}
        >
          {/* Thumbhash placeholder */}
          {thumbhashUrl && (
            <img
              src={thumbhashUrl}
              alt=""
              draggable={false}
              className="absolute inset-0 w-full h-full object-cover"
              aria-hidden
            />
          )}
          {/* Actual image */}
          <img
            src={img.thumb_path || ''}
            alt=""
            loading="lazy"
            draggable={false}
            className="absolute inset-0 w-full h-full object-cover transition-opacity duration-300"
            onLoad={(e) => {
              e.currentTarget.style.opacity = '1'
            }}
            style={{ opacity: img.thumbhash ? 0 : undefined }}
          />
          {/* Favorite indicator */}
          {favorited && (
            <div className="absolute top-1 right-1 z-10">
              <Heart className="w-4 h-4 fill-red-500 text-red-500 drop-shadow-md" />
            </div>
          )}
          {/* Selection highlight */}
          {isSelected && (
            <div className="absolute inset-0 z-20 border-2 border-vault-accent rounded-sm" />
          )}
          {/* Hover overlay */}
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors" />
        </button>
      )
    },
    [
      handleImageClick,
      thumbhashUrls,
      lpStart,
      lpMove,
      lpEnd,
      lpMenu,
      isFavorited,
      imageMenu?.imageId,
    ],
  )

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
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
            </div>
          )}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={favoritedFilter}
              onChange={(e) => setFavoritedFilter(e.target.checked)}
              className="w-4 h-4 accent-yellow-500"
            />
            <span className="text-sm text-vault-text-secondary">{t('images.favoritesOnly')}</span>
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddTag()
              }}
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
          <div className="text-center text-vault-text-secondary py-12">{t('images.noResults')}</div>
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

      {imageMenu?.open && (
        <ImageContextMenu
          open={true}
          onClose={() => setImageMenu(null)}
          position={imageMenu.position}
          imageUrl={imageMenu.imageUrl}
          imageName={imageMenu.imageName}
          onHide={imageMenu.source ? handleHideImage : undefined}
          isFavorited={isFavorited(imageMenu.imageId)}
          onToggleFavorite={handleToggleFavorite}
          onViewGallery={imageMenu.source && imageMenu.sourceId ? handleViewGallery : undefined}
          onFindSource={() => {
            setSaucenaoImageId(imageMenu.imageId)
            setImageMenu(null)
          }}
        />
      )}

      {saucenaoImageId && (
        <SauceNaoModal imageId={saucenaoImageId} onClose={() => setSaucenaoImageId(null)} />
      )}
    </div>
  )
}
