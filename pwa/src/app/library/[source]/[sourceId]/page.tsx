'use client'

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { toast } from 'sonner'
import useSWR from 'swr'
import { useLibraryGallery, useInfiniteGalleryImages, useUpdateGallery } from '@/hooks/useGalleries'
import { useTagTranslations } from '@/hooks/useTagTranslations'
import { api } from '@/lib/api'
import { useWsConnection, useWsJobs } from '@/lib/ws'
import { pollingRefreshInterval } from '@/lib/wsPolling'
import { decodeRouteSegment, readerHref } from '@/lib/galleryRoutes'
import { GalleryTagSection } from '@/components/library/GalleryTagSection'
import { AppImage } from '@/components/AppImage'
import type { GalleryImage } from '@/lib/types'
import { ImageContextMenu } from '@/components/Reader/ImageContextMenu'
import { useLongPress } from '@/hooks/useLongPress'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { RatingStars } from '@/components/RatingStars'
import { t, formatDate } from '@/lib/i18n'
import { BackButton } from '@/components/BackButton'
import {
  Heart,
  Bookmark,
  BookmarkCheck,
  Sparkles,
  X,
  Share2,
  GitMerge,
  History,
} from 'lucide-react'
import { SimilarImagesPanel } from '@/components/SimilarImagesPanel'
import { LazySauceNaoModal } from '@/components/LazyDialogs'
import { VirtualGrid } from '@/components/VirtualGrid'

function getSourceLink(sourceUrl: string, source: string): { href: string; external: boolean } {
  if (source === 'ehentai') {
    const match = sourceUrl.match(/\/g\/(\d+)\/([a-f0-9]+)/)
    if (match) return { href: `/e-hentai/${match[1]}/${match[2]}`, external: false }
  }
  if (source === 'pixiv') {
    const match = sourceUrl.match(/artworks\/(\d+)/)
    if (match) return { href: `/pixiv/illust/${match[1]}`, external: false }
  }
  return { href: sourceUrl, external: true }
}

function getArtistDisplayName(gallery: {
  artist_id?: string | null
  artist_name?: string | null
}): string {
  if (gallery.artist_name?.trim()) return gallery.artist_name.trim()
  const artistId = gallery.artist_id?.trim()
  if (!artistId) return ''
  const separatorIndex = artistId.indexOf(':')
  return separatorIndex >= 0 ? artistId.slice(separatorIndex + 1) : artistId
}

function formatSearchFilterValue(value: string): string {
  const escaped = value.replace(/"/g, '\\"')
  return /\s/.test(escaped) ? `"${escaped}"` : escaped
}

function artistSearchHref(artistId: string): string {
  return `/library?q=${encodeURIComponent(`artist_id:${formatSearchFilterValue(artistId)}`)}`
}
const DOWNLOAD_STATUS_LABELS: Record<string, { labelKey: string; className: string }> = {
  complete: {
    labelKey: 'library.statusComplete',
    className: 'bg-green-900/40 border-green-700/50 text-green-400',
  },
  partial: {
    labelKey: 'library.statusPartial',
    className: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-400',
  },
  proxy_only: {
    labelKey: 'library.statusProxyOnly',
    className: 'bg-gray-800 border-gray-600 text-gray-400',
  },
  downloading: {
    labelKey: 'library.statusDownloading',
    className: 'bg-blue-900/40 border-blue-700/50 text-blue-400',
  },
}

export default function GalleryDetailPage() {
  const params = useParams<{ source: string; sourceId: string }>()
  const router = useRouter()
  const source = decodeRouteSegment(params?.source)
  const sourceId = decodeRouteSegment(params?.sourceId)
  const { connected } = useWsConnection()
  const { lastJobUpdate } = useWsJobs()

  const {
    data: gallery,
    isLoading: galleryLoading,
    error: galleryError,
    mutate: mutateGallery,
  } = useLibraryGallery(source, sourceId)
  const {
    data: imagesData,
    isLoading: imagesLoading,
    isLoadingMore: imagesLoadingMore,
    isReachingEnd: imagesReachingEnd,
    loadMore: loadMoreImages,
    mutate: mutateImages,
  } = useInfiniteGalleryImages(source, sourceId, { limit: 120 })
  const { trigger: updateGallery, isMutating: isUpdating } = useUpdateGallery(
    source ?? '',
    sourceId ?? '',
  )
  const { data: tagTranslations } = useTagTranslations(gallery?.tags_array ?? [])
  const { data: featureSettings } = useSWR('settings/features', () => api.settings.getFeatures(), {
    revalidateOnFocus: false,
    dedupingInterval: 300000, // 5 min cache
  })
  // Plugin health, sharing, and version data are only read by panels the user has
  // to open first. Fetching them on mount cost three requests on every gallery
  // view for data most views never showed.
  const [upscaleOpen, setUpscaleOpen] = useState(false)
  const { data: pluginHealth, isLoading: pluginHealthLoading } = useSWR(
    upscaleOpen ? 'plugins/health' : null,
    () => api.plugins.health(),
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    },
  )
  const [versionsOpen, setVersionsOpen] = useState(false)
  const { data: versionData, mutate: mutateVersions } = useSWR(
    gallery?.id && versionsOpen ? ['gallery-versions', gallery.id] : null,
    () => api.galleryManagement.versions(gallery!.id),
    { revalidateOnFocus: false },
  )
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false)
  const [pagesOutdated, setPagesOutdated] = useState<{ old: number; new: number } | null>(null)
  const updateCheckedRef = useRef<boolean>(false)
  const [isEnqueueingUpdate, setIsEnqueueingUpdate] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isRetagging, setIsRetagging] = useState(false)
  const [tagData, setTagData] = useState<
    Array<{ namespace: string; name: string; confidence: number; source: string }>
  >([])
  const images = imagesData?.images ?? []

  // Image multi-select & exclusion state
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  // Index (into `images`) of the last toggled tile — anchor for range selection
  const selectAnchorRef = useRef<number | null>(null)
  const [isHiding, setIsHiding] = useState(false)
  const [excludedBlobs, setExcludedBlobs] = useState<
    Array<{ blob_sha256: string; excluded_at: string | null }>
  >([])
  const [hiddenImages, setHiddenImages] = useState<GalleryImage[]>([])
  const [showExcluded, setShowExcluded] = useState(false)
  const [restoringHash, setRestoringHash] = useState<string | null>(null)
  const [restoringImageId, setRestoringImageId] = useState<number | null>(null)
  const [upscaleImageId, setUpscaleImageId] = useState<number | null>(null)
  const [upscaleModel, setUpscaleModel] = useState('')
  const [upscaleScale, setUpscaleScale] = useState(2)
  const [upscaleSubmitting, setUpscaleSubmitting] = useState(false)

  // Image context menu state
  const [imageMenu, setImageMenu] = useState<{
    open: boolean
    position: { x: number; y: number }
    imageUrl: string
    imageName: string
    imageId: number
    pageNum: number
  } | null>(null)

  const activeImageRef = useRef<GalleryImage | null>(null)

  // Similar images modal state
  const [similarImageId, setSimilarImageId] = useState<number | null>(null)
  // SauceNAO modal state
  const [saucenaoImageId, setSaucenaoImageId] = useState<number | null>(null)

  // Track favorited image IDs from API response + optimistic overrides
  const [localFavOverrides, setLocalFavOverrides] = useState<Map<number, boolean>>(new Map())

  const favoritedImageIds = useMemo(() => {
    const set = new Set(imagesData?.favorited_image_ids ?? [])
    for (const [id, fav] of localFavOverrides) {
      if (fav) set.add(id)
      else set.delete(id)
    }
    return set
  }, [imagesData?.favorited_image_ids, localFavOverrides])

  const isFavorited = useCallback(
    (imageId: number) => favoritedImageIds.has(imageId),
    [favoritedImageIds],
  )

  // Inline-edit state
  const [editingTitle, setEditingTitle] = useState(false)
  const [editTitleValue, setEditTitleValue] = useState('')
  const [editingTitleJpn, setEditingTitleJpn] = useState(false)
  const [editTitleJpnValue, setEditTitleJpnValue] = useState('')

  // Record browse history once when gallery data is loaded
  const historyRecordedRef = useRef(false)
  useEffect(() => {
    if (!gallery || historyRecordedRef.current) return
    try {
      if (typeof window !== 'undefined' && localStorage.getItem('history_enabled') !== 'false') {
        historyRecordedRef.current = true
        api.history
          .record({
            source: gallery.source,
            source_id: gallery.source_id,
            title: gallery.title,
            thumb: gallery.cover_thumb || undefined,
          })
          .catch(() => {})
      }
    } catch {
      // localStorage may be unavailable in some contexts
    }
  }, [gallery])

  // Auto-check gallery metadata update (once per page visit)
  useEffect(() => {
    if (!gallery || !featureSettings || updateCheckedRef.current) return
    // Only EH and Pixiv galleries support metadata check
    if (!['ehentai', 'pixiv'].includes(gallery.source)) {
      updateCheckedRef.current = true
      return
    }
    const checkDays: number =
      (featureSettings as unknown as Record<string, number>).gallery_update_check_days ?? -1
    if (checkDays === -1) {
      updateCheckedRef.current = true
      return
    }
    let shouldCheck = false
    if (checkDays === 0) {
      shouldCheck = true
    } else {
      const updatedAt = gallery.metadata_updated_at
      if (!updatedAt) {
        shouldCheck = true
      } else {
        const diffMs = Date.now() - new Date(updatedAt).getTime()
        const diffDays = diffMs / (1000 * 60 * 60 * 24)
        if (diffDays >= checkDays) shouldCheck = true
      }
    }
    if (!shouldCheck) {
      updateCheckedRef.current = true
      return
    }
    setIsCheckingUpdate(true)
    api.library
      .checkUpdate(gallery.source, gallery.source_id)
      .then((result) => {
        if (result.status === 'updated') {
          mutateGallery()
          if (result.pages_diff) {
            toast.success(
              t('library.metadataPagesChanged', {
                old: String(result.pages_diff.old),
                new: String(result.pages_diff.new),
              }),
            )
            if (result.pages_diff.new > result.pages_diff.old) {
              setPagesOutdated(result.pages_diff)
            }
          } else {
            const fields = result.changed_fields?.join(', ') ?? ''
            toast.success(t('library.metadataFieldsUpdated', { fields }))
          }
        }
      })
      .catch(() => {})
      .finally(() => {
        setIsCheckingUpdate(false)
        updateCheckedRef.current = true
      })
  }, [gallery, featureSettings, mutateGallery])

  const handleEnqueueUpdate = useCallback(async () => {
    if (!gallery?.source_url || isEnqueueingUpdate || activeJobId) return
    setIsEnqueueingUpdate(true)
    try {
      const result = await api.download.enqueue(gallery.source_url)
      toast.success(t('library.updateEnqueued'))
      setPagesOutdated(null)
      setActiveJobId(result.job_id)
    } catch {
      toast.error(t('library.updateFailed'))
    } finally {
      setIsEnqueueingUpdate(false)
    }
  }, [gallery?.source_url, isEnqueueingUpdate, activeJobId])

  const refetchTagData = useCallback(() => {
    if (!source || !sourceId) return
    api.library
      .getGalleryTags(source, sourceId)
      .then((res) => setTagData(res.tags))
      .catch(() => {})
  }, [source, sourceId])

  useEffect(() => {
    refetchTagData()
  }, [refetchTagData])

  const handleUpdateTag = useCallback(
    async (tagStr: string, action: 'add' | 'remove') => {
      if (!gallery) return
      try {
        await api.tags.updateGalleryTags(gallery.id, { tags: [tagStr], action })
        toast.success(t(action === 'add' ? 'library.tagAdded' : 'library.tagRemoved'))
        mutateGallery()
        refetchTagData()
      } catch {
        toast.error(t(action === 'add' ? 'library.tagAddFailed' : 'library.tagRemoveFailed'))
      }
    },
    [gallery, mutateGallery, refetchTagData],
  )

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      )
        return
      if (selectMode) return
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        if (gallery?.source && gallery?.source_id) {
          router.push(readerHref(gallery.source, gallery.source_id))
        }
      }
      if (e.key === 'ArrowUp' || e.key === 'Escape') {
        e.preventDefault()
        if (history.length > 1) {
          router.back()
        } else {
          router.push('/library')
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [gallery?.source, gallery?.source_id, router, selectMode])

  const isDownloading = gallery?.download_status === 'downloading'
  // Fallback poll — only runs when WS is down. While connected, the effect
  // below reacts to WS job-progress events instead (see wsInvalidation.tsx
  // module docstring for why download.* can't drive this via lastEvent).
  useEffect(() => {
    if (!isDownloading || connected) return
    const interval = setInterval(() => {
      mutateGallery()
      mutateImages()
    }, 5000)
    return () => clearInterval(interval)
  }, [isDownloading, connected, mutateGallery, mutateImages])

  // WS-driven refresh while downloading: progressive import sets
  // progress.gallery_id on job_update events (see worker/download.py) so a
  // matching update means new pages may have arrived for this gallery.
  useEffect(() => {
    if (!isDownloading || !gallery || !lastJobUpdate) return
    const progressGalleryId = lastJobUpdate.progress?.gallery_id
    if (progressGalleryId !== gallery.id) return
    mutateGallery()
    mutateImages()
  }, [lastJobUpdate, isDownloading, gallery, mutateGallery, mutateImages])

  const { data: activeJob, mutate: mutateActiveJob } = useSWR(
    activeJobId ? ['download/job', activeJobId] : null,
    ([, id]) => api.download.getJob(id),
    { refreshInterval: pollingRefreshInterval(connected, 3000), revalidateOnFocus: false },
  )
  // While connected, a matching job_update is a more precise (and instant)
  // signal than the polling fallback above.
  useEffect(() => {
    if (!activeJobId || !lastJobUpdate || lastJobUpdate.job_id !== activeJobId) return
    mutateActiveJob()
  }, [lastJobUpdate, activeJobId, mutateActiveJob])
  useEffect(() => {
    if (!activeJob) return
    const terminal = ['done', 'failed', 'cancelled', 'partial']
    if (terminal.includes(activeJob.status)) {
      setActiveJobId(null)
      mutateGallery()
      mutateImages()
    }
  }, [activeJob, mutateGallery, mutateImages])

  const getDeleteConfirmKey = () => {
    if (gallery?.import_mode === 'link') return 'library.delete.link.confirm'
    if (gallery?.import_mode === 'copy') return 'library.delete.copy.confirm'
    return 'library.delete.download.confirm'
  }

  const handleDelete = async () => {
    if (!gallery || !source || !sourceId) return
    const confirmMsg = t(getDeleteConfirmKey(), { title: gallery.title })
    if (!confirm(confirmMsg)) return
    setIsDeleting(true)
    try {
      await api.library.deleteGallery(source, sourceId)
      toast.success(t('library.deleted'))
      router.push('/library')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : t('library.deleteFailed')
      toast.error(msg)
    } finally {
      setIsDeleting(false)
    }
  }

  const handleRetag = async () => {
    if (!gallery) return
    setIsRetagging(true)
    try {
      await api.tags.retag(gallery.id)
      toast.success(t('library.retagQueued'))
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : t('library.retagFailed')
      toast.error(msg)
    } finally {
      setIsRetagging(false)
    }
  }

  const handleTitleSave = useCallback(
    async (field: 'title' | 'title_jpn', value: string) => {
      if (!gallery) return
      const original = field === 'title' ? gallery.title : (gallery.title_jpn ?? '')
      if (value === original) return
      try {
        const updated = await updateGallery({ [field]: value })
        if (updated) mutateGallery(updated, false)
        toast.success(t('library.titleUpdated'))
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [gallery, updateGallery, mutateGallery],
  )

  const handleCategoryChange = useCallback(
    async (category: string) => {
      if (!gallery || category === gallery.category) return
      try {
        const updated = await updateGallery({ category })
        if (updated) mutateGallery(updated, false)
        toast.success(t('library.categoryUpdated'))
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [gallery, updateGallery, mutateGallery],
  )

  const handleFavoriteToggle = async () => {
    if (!gallery) return
    try {
      const updated = await updateGallery({ favorited: !gallery.is_favorited })
      if (updated) mutateGallery(updated, false)
    } catch {
      toast.error(t('library.favoriteError'))
    }
  }

  const handleRatingChange = async (newRating: number) => {
    if (!gallery) return
    try {
      const updated = await updateGallery({ rating: newRating })
      if (updated) mutateGallery(updated, false)
    } catch {
      toast.error(t('library.ratingError'))
    }
  }

  // Toggle a single image and move the range anchor to it
  const toggleSelect = (image: GalleryImage, idx: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(image.id)) next.delete(image.id)
      else next.add(image.id)
      return next
    })
    selectAnchorRef.current = idx
  }

  // Select everything between the anchor and idx (shift-click / long-press)
  const rangeSelectTo = (idx: number) => {
    const anchor = selectAnchorRef.current
    const lo = anchor === null ? idx : Math.min(anchor, idx)
    const hi = anchor === null ? idx : Math.max(anchor, idx)
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (let i = lo; i <= hi; i++) {
        const img = images[i]
        if (img) next.add(img.id)
      }
      return next
    })
    selectAnchorRef.current = idx
  }

  const selectAllLoaded = () => {
    setSelectedIds(new Set(images.map((img) => img.id)))
  }

  const invertSelection = () => {
    setSelectedIds(
      (prev) => new Set(images.filter((img) => !prev.has(img.id)).map((img) => img.id)),
    )
  }

  const exitSelectMode = () => {
    setSelectMode(false)
    setSelectedIds(new Set())
    selectAnchorRef.current = null
  }

  const enterSelectModeWith = (imageId: number) => {
    setSelectMode(true)
    setSelectedIds(new Set([imageId]))
    const idx = images.findIndex((img) => img.id === imageId)
    selectAnchorRef.current = idx >= 0 ? idx : null
  }

  // Batch hide selected images in one request, with undo instead of confirm
  const handleHideSelected = async () => {
    if (!source || !sourceId || selectedIds.size === 0) return
    const src = source
    const sid = sourceId
    const ids = [...selectedIds]
    setIsHiding(true)
    try {
      const res = await api.library.hideImagesBatch(src, sid, ids)
      exitSelectMode()
      toast.success(t('library.imagesHidden', { count: res.hidden }), {
        action: {
          label: t('common.undo'),
          onClick: async () => {
            try {
              await api.library.restoreImagesBatch(src, sid, ids)
              toast.success(t('library.hiddenRestored'))
              mutateGallery()
              mutateImages()
              fetchHidden()
            } catch {
              toast.error(t('library.restoreFailed'))
            }
          },
        },
      })
      mutateGallery()
      mutateImages()
      fetchExcluded()
      fetchHidden()
    } catch {
      toast.error(t('library.hideImageFailed'))
    } finally {
      setIsHiding(false)
    }
  }

  // Fetch excluded blobs
  const fetchExcluded = useCallback(async () => {
    if (!source || !sourceId) return
    try {
      const res = await api.library.listExcluded(source, sourceId)
      setExcludedBlobs(res.excluded)
    } catch {
      setExcludedBlobs([])
    }
  }, [source, sourceId])

  const fetchHidden = useCallback(async () => {
    if (!source || !sourceId) return
    try {
      const res = await api.library.listHidden(source, sourceId)
      setHiddenImages(res.images)
    } catch {
      setHiddenImages([])
    }
  }, [source, sourceId])

  useEffect(() => {
    fetchExcluded()
    fetchHidden()
  }, [fetchExcluded, fetchHidden])

  // Restore excluded blob
  const handleRestore = async (sha256: string) => {
    if (!source || !sourceId) return
    if (!confirm(t('library.restoreConfirm'))) return
    setRestoringHash(sha256)
    try {
      await api.library.restoreExcluded(source, sourceId, sha256)
      toast.success(t('library.restored'))
      setExcludedBlobs((prev) => prev.filter((b) => b.blob_sha256 !== sha256))
    } catch {
      toast.error(t('library.restoreFailed'))
    } finally {
      setRestoringHash(null)
    }
  }

  const handleRestoreImage = async (imageId: number) => {
    setRestoringImageId(imageId)
    try {
      await api.library.restoreImage(imageId)
      toast.success(t('library.hiddenRestored'))
      setHiddenImages((prev) => prev.filter((img) => img.id !== imageId))
      mutateGallery()
      mutateImages()
    } catch {
      toast.error(t('library.restoreFailed'))
    } finally {
      setRestoringImageId(null)
    }
  }

  // Long-press handler to open image context menu (non-select mode)
  const handleImageLongPress = useCallback((e: React.TouchEvent | React.MouseEvent) => {
    const img = activeImageRef.current
    if (!img) return
    const pos =
      'touches' in e
        ? { x: e.touches[0].clientX, y: e.touches[0].clientY }
        : { x: (e as React.MouseEvent).clientX, y: (e as React.MouseEvent).clientY }
    setImageMenu({
      open: true,
      position: pos,
      imageUrl: img.file_path || img.thumb_path || '',
      imageName: img.filename || `page_${img.page_num}`,
      imageId: img.id,
      pageNum: img.page_num,
    })
  }, [])

  const {
    onTouchStart: lpStart,
    onTouchMove: lpMove,
    onTouchEnd: lpEnd,
    onContextMenu: lpCtx,
  } = useLongPress({ onLongPress: handleImageLongPress })

  // In select mode, long-press (touch) or right-click extends the selection
  // from the anchor to the pressed tile — touch parity with shift-click.
  const selectLpTargetRef = useRef<number | null>(null)
  const handleSelectLongPress = () => {
    const idx = selectLpTargetRef.current
    if (idx !== null) rangeSelectTo(idx)
  }
  const {
    onTouchStart: selLpStart,
    onTouchMove: selLpMove,
    onTouchEnd: selLpEnd,
    onContextMenu: selLpCtx,
  } = useLongPress({ onLongPress: handleSelectLongPress })

  const handleImageToggleFavorite = useCallback(async () => {
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
      mutateImages()
    } catch {
      // Revert optimistic update
      setLocalFavOverrides((prev) => {
        const next = new Map(prev)
        next.delete(imageId)
        return next
      })
      toast.error(t('reader.favoriteFailed'))
    }
  }, [imageMenu, isFavorited, mutateImages])

  const handleImageHide = useCallback(async () => {
    if (!imageMenu || !source || !sourceId) return
    const { imageId } = imageMenu
    setImageMenu(null)

    try {
      await api.library.hideImage(imageId)
      toast.success(t('reader.imageHidden'), {
        action: {
          label: t('common.undo'),
          onClick: async () => {
            try {
              await api.library.restoreImage(imageId)
              toast.success(t('library.hiddenRestored'))
              mutateGallery()
              mutateImages()
              fetchHidden()
            } catch {
              toast.error(t('library.restoreFailed'))
            }
          },
        },
      })
      mutateGallery()
      mutateImages()
      fetchExcluded()
      fetchHidden()
    } catch {
      toast.error(t('common.error'))
    }
  }, [imageMenu, source, sourceId, mutateGallery, mutateImages, fetchExcluded, fetchHidden])

  if (galleryLoading) {
    return (
      <div className="min-h-screen bg-vault-bg flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (galleryError) {
    return (
      <div className="min-h-screen bg-vault-bg flex items-center justify-center">
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-6 text-red-400 max-w-md text-center">
          <p className="font-semibold mb-2">{t('library.failedToLoad')}</p>
          <p className="text-sm">{galleryError.message}</p>
          <button
            onClick={() => router.back()}
            className="mt-4 px-4 py-2 bg-vault-input border border-vault-border rounded text-vault-text-secondary text-sm hover:text-vault-text transition-colors"
          >
            {t('common.goBack')}
          </button>
        </div>
      </div>
    )
  }

  if (!gallery) return null

  const statusInfo =
    DOWNLOAD_STATUS_LABELS[gallery.download_status] ?? DOWNLOAD_STATUS_LABELS.proxy_only
  const artistDisplayName = getArtistDisplayName(gallery)

  return (
    <div>
      {/* Back */}
      <BackButton fallback="/library" />

      {/* Header */}
      <div className="bg-vault-card border border-vault-border rounded-xl p-5 mb-5">
        <div className="flex flex-col md:flex-row gap-5">
          {/* Thumbnail preview from first image */}
          <div className="shrink-0">
            {images[0]?.thumb_path ? (
              <AppImage
                src={images[0].thumb_path}
                alt={gallery.title}
                className="w-40 h-56 object-cover rounded"
                sizes="160px"
              />
            ) : (
              <div className="w-40 h-56 bg-vault-input rounded flex items-center justify-center text-vault-text-muted text-xs">
                {t('library.noCover')}
              </div>
            )}
          </div>

          {/* Meta */}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2 mb-1">
              {editingTitle ? (
                <input
                  autoFocus
                  value={editTitleValue}
                  onChange={(e) => setEditTitleValue(e.target.value)}
                  onBlur={async () => {
                    await handleTitleSave('title', editTitleValue)
                    setEditingTitle(false)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.currentTarget.blur()
                    if (e.key === 'Escape') setEditingTitle(false)
                  }}
                  className="text-xl font-bold text-vault-text leading-tight bg-vault-input border border-vault-border rounded px-2 py-1 w-full focus:outline-none focus:border-vault-accent"
                />
              ) : (
                <h1
                  onClick={() => {
                    setEditTitleValue(gallery.title)
                    setEditingTitle(true)
                  }}
                  className="text-xl font-bold text-vault-text leading-tight cursor-pointer hover:text-vault-accent transition-colors"
                  title={t('library.editTitle')}
                >
                  {gallery.title}
                </h1>
              )}
              {pagesOutdated && gallery.download_status === 'complete' ? (
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="px-2 py-0.5 rounded border text-xs font-medium bg-orange-900/40 border-orange-700/50 text-orange-400">
                    {t('library.statusOutdated')}
                  </span>
                  {gallery.source_url && (
                    <button
                      onClick={handleEnqueueUpdate}
                      disabled={isEnqueueingUpdate || !!activeJobId}
                      className="px-2 py-0.5 rounded border text-xs font-medium bg-vault-accent/20 border-vault-accent/50 text-vault-accent hover:bg-vault-accent/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isEnqueueingUpdate ? '...' : t('library.updateNow')}
                    </button>
                  )}
                </div>
              ) : (
                <span
                  className={`shrink-0 px-2 py-0.5 rounded border text-xs font-medium ${statusInfo.className}`}
                >
                  {t(statusInfo.labelKey)}
                </span>
              )}
            </div>
            {(gallery.title_jpn || editingTitleJpn) &&
              (editingTitleJpn ? (
                <input
                  autoFocus
                  value={editTitleJpnValue}
                  onChange={(e) => setEditTitleJpnValue(e.target.value)}
                  onBlur={async () => {
                    await handleTitleSave('title_jpn', editTitleJpnValue)
                    setEditingTitleJpn(false)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.currentTarget.blur()
                    if (e.key === 'Escape') setEditingTitleJpn(false)
                  }}
                  className="text-sm text-vault-text-secondary mb-3 bg-vault-input border border-vault-border rounded px-2 py-1 w-full focus:outline-none focus:border-vault-accent"
                />
              ) : (
                <p
                  onClick={() => {
                    setEditTitleJpnValue(gallery.title_jpn ?? '')
                    setEditingTitleJpn(true)
                  }}
                  className="text-sm text-vault-text-secondary mb-3 cursor-pointer hover:text-vault-accent transition-colors"
                  title={t('library.editTitle')}
                >
                  {gallery.title_jpn}
                </p>
              ))}

            {/* Meta grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 text-sm mb-4">
              {[
                { labelKey: 'library.metaSource', value: gallery.source },
                { labelKey: 'library.metaLanguage', value: gallery.language || 'N/A' },
                { labelKey: 'library.metaPages', value: String(gallery.pages) },
                {
                  labelKey: 'library.metaAdded',
                  value: formatDate(gallery.added_at),
                },
                ...(gallery.posted_at
                  ? [{ labelKey: 'library.metaPosted', value: formatDate(gallery.posted_at) }]
                  : []),
              ].map(({ labelKey, value }) => (
                <div key={labelKey}>
                  <span className="text-vault-text-muted">{t(labelKey)}: </span>
                  <span className="text-vault-text">{value}</span>
                </div>
              ))}
              {/* Category — inline select */}
              <div>
                <span className="text-vault-text-muted">{t('library.metaCategory')}: </span>
                <select
                  value={gallery.category}
                  onChange={(e) => handleCategoryChange(e.target.value)}
                  className="bg-vault-input border border-vault-border rounded px-1 py-0.5 text-vault-text text-sm focus:outline-none"
                >
                  <option value="">{t('library.categoryUncategorized')}</option>
                  {[
                    'Doujinshi',
                    'Manga',
                    'Artist CG',
                    'Game CG',
                    'Western',
                    'Non-H',
                    'Image Set',
                    'Cosplay',
                    'Asian Porn',
                    'Misc',
                  ].map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
              </div>
              {/* Artist and uploader have distinct meanings on E-Hentai. */}
              <div>
                <span className="text-vault-text-muted">{t('library.artistFilter')}: </span>
                {gallery.artist_id && artistDisplayName ? (
                  <Link
                    href={artistSearchHref(gallery.artist_id)}
                    className="text-vault-text hover:text-vault-accent hover:underline transition-colors"
                  >
                    {artistDisplayName}
                  </Link>
                ) : (
                  <span className="text-vault-text">N/A</span>
                )}
              </div>
              <div>
                <span className="text-vault-text-muted">{t('library.metaUploader')}: </span>
                <span className="text-vault-text">{gallery.uploader || 'N/A'}</span>
              </div>
            </div>

            {/* Rating */}
            <div className="flex items-center gap-3 mb-4">
              <span className="text-sm text-vault-text-muted">{t('library.metaRating')}</span>
              <RatingStars
                rating={gallery.my_rating ?? 0}
                readonly={isUpdating}
                onChange={handleRatingChange}
              />
              <span className="text-sm text-vault-text-secondary">
                {(gallery.my_rating ?? 0).toFixed(1)}
              </span>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-wrap gap-2">
              <Link
                href={readerHref(gallery.source, gallery.source_id)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-medium transition-colors"
              >
                {t('browse.read')}
              </Link>
              {gallery.artist_id && (
                <Link
                  href={artistSearchHref(gallery.artist_id)}
                  className="px-4 py-2 rounded text-sm font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:border-vault-accent hover:text-vault-accent transition-colors"
                >
                  {t('library.viewAllByArtist')}
                </Link>
              )}
              {gallery.source_url &&
                (() => {
                  const { href, external } = getSourceLink(gallery.source_url, gallery.source)
                  const btnClass =
                    'px-4 py-2 rounded text-sm font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:border-vault-accent hover:text-vault-accent transition-colors'
                  return external ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className={btnClass}>
                      {t('library.viewSource')}
                    </a>
                  ) : (
                    <Link href={href} className={btnClass}>
                      {t('library.viewSource')}
                    </Link>
                  )
                })()}
              <button
                onClick={handleFavoriteToggle}
                disabled={isUpdating}
                className={`px-4 py-2 rounded text-sm font-medium border transition-colors ${
                  gallery.is_favorited
                    ? 'bg-yellow-900/40 border-yellow-600 text-yellow-400 hover:bg-yellow-900/60'
                    : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-yellow-600 hover:text-yellow-400'
                }`}
              >
                {gallery.is_favorited ? t('library.favorited') : t('library.unfavorited')}
              </button>
              <button
                onClick={async () => {
                  try {
                    const updated = await api.library.updateGallery(source!, sourceId!, {
                      in_reading_list: !gallery.in_reading_list,
                    })
                    mutateGallery(updated, false)
                    toast.success(
                      gallery.in_reading_list
                        ? t('contextMenu.removeFromReadingList')
                        : t('contextMenu.addToReadingList'),
                    )
                  } catch {
                    toast.error(t('common.failedToLoad'))
                  }
                }}
                disabled={isUpdating}
                title={
                  gallery.in_reading_list ? t('library.inReadingList') : t('library.readLater')
                }
                className={`px-4 py-2 rounded text-sm font-medium border transition-colors flex items-center gap-1.5 ${
                  gallery.in_reading_list
                    ? 'bg-blue-900/40 border-blue-600 text-blue-400 hover:bg-blue-900/60'
                    : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-blue-600 hover:text-blue-400'
                }`}
              >
                {gallery.in_reading_list ? (
                  <>
                    <BookmarkCheck size={16} />
                    {t('library.inReadingList')}
                  </>
                ) : (
                  <>
                    <Bookmark size={16} />
                    {t('library.readLater')}
                  </>
                )}
              </button>
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                className="px-4 py-2 rounded text-sm font-medium border bg-red-900/30 border-red-700/50 text-red-400 hover:bg-red-900/50 transition-colors disabled:opacity-50"
              >
                {isDeleting
                  ? t('library.deleting')
                  : gallery.import_mode === 'link'
                    ? t('library.delete.link.button')
                    : t('library.delete')}
              </button>
              <button
                onClick={handleRetag}
                disabled={isRetagging}
                className="px-4 py-2 rounded text-sm font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:border-purple-600 hover:text-purple-400 transition-colors disabled:opacity-50"
              >
                {isRetagging ? t('library.retagging') : t('library.retag')}
              </button>
              {featureSettings?.swarmui_enabled && (
                <button
                  type="button"
                  onClick={() => {
                    setUpscaleImageId(images[0]?.id ?? null)
                    setUpscaleOpen(true)
                  }}
                  disabled={images.length === 0}
                  title={t('library.aiUpscale')}
                  className="flex items-center gap-1.5 rounded border border-purple-600/60 bg-purple-900/30 px-4 py-2 text-sm font-medium text-purple-300 transition-colors hover:bg-purple-900/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Sparkles size={16} />
                  {t('library.aiUpscale')}
                </button>
              )}
              <button
                type="button"
                className="flex items-center gap-1.5 rounded border border-vault-border bg-vault-input px-4 py-2 text-sm text-vault-text-secondary hover:border-vault-accent"
                onClick={async () => {
                  if (!gallery) return
                  try {
                    const result = await api.galleryManagement.createShare(gallery.id, 168, true)
                    const absolute = `${window.location.origin}${result.url}`
                    await navigator.clipboard.writeText(absolute)
                    toast.success(t('library.shareCopied'))
                  } catch (error) {
                    toast.error(error instanceof Error ? error.message : String(error))
                  }
                }}
              >
                <Share2 size={16} /> {t('library.share')}
              </button>
              <button
                type="button"
                className="flex items-center gap-1.5 rounded border border-vault-border bg-vault-input px-4 py-2 text-sm text-vault-text-secondary hover:border-vault-accent"
                onClick={async () => {
                  if (!gallery) return
                  const sharing = await api.galleryManagement.sharing(gallery.id)
                  const raw = window.prompt(
                    t('library.accessUserIds'),
                    sharing.permissions.map((item) => item.user_id).join(','),
                  )
                  if (raw === null) return
                  const permissions = raw
                    .split(',')
                    .map((value) => Number(value.trim()))
                    .filter(Number.isInteger)
                    .map((user_id) => ({ user_id, can_edit: false }))
                  const visibility = window.confirm(t('library.privateVisibilityConfirm'))
                    ? 'private'
                    : 'public'
                  await api.galleryManagement.updateSharing(gallery.id, { visibility, permissions })
                  toast.success(t('library.accessUpdated'))
                }}
              >
                {t('library.manageAccess')}
              </button>
              <button
                type="button"
                className="flex items-center gap-1.5 rounded border border-vault-border bg-vault-input px-4 py-2 text-sm text-vault-text-secondary hover:border-vault-accent"
                onClick={() => setVersionsOpen((open) => !open)}
              >
                <History size={16} /> {t('library.versions')}
              </button>
              {versionsOpen && (
                <button
                  type="button"
                  className="flex items-center gap-1.5 rounded border border-vault-border bg-vault-input px-4 py-2 text-sm text-vault-text-secondary hover:border-vault-accent"
                  onClick={async () => {
                    if (!gallery) return
                    const value = window.prompt(t('library.linkVersionPrompt'))
                    const linkedId = Number(value)
                    if (!Number.isInteger(linkedId)) return
                    await api.galleryManagement.linkVersion(gallery.id, linkedId)
                    await mutateVersions()
                    toast.success(t('library.versionLinked'))
                  }}
                >
                  <History size={16} /> {t('library.linkVersion')}
                </button>
              )}
              <button
                type="button"
                className="flex items-center gap-1.5 rounded border border-red-700/50 bg-red-900/20 px-4 py-2 text-sm text-red-300 hover:bg-red-900/40"
                onClick={async () => {
                  if (!gallery) return
                  const value = window.prompt(t('library.mergeGalleryPrompt'))
                  const sourceGalleryId = Number(value)
                  if (
                    !Number.isInteger(sourceGalleryId) ||
                    !window.confirm(t('library.mergeGalleryConfirm'))
                  )
                    return
                  await api.galleryManagement.merge(gallery.id, sourceGalleryId)
                  await Promise.all([mutateGallery(), mutateImages()])
                  toast.success(t('library.galleryMerged'))
                }}
              >
                <GitMerge size={16} /> {t('library.merge')}
              </button>
            </div>
            {versionsOpen && versionData?.versions && versionData.versions.length > 1 && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                <span className="text-vault-text-muted">{t('library.versions')}:</span>
                {versionData.versions.map((version) => (
                  <Link
                    key={version.id}
                    href={`/library/${encodeURIComponent(version.source)}/${encodeURIComponent(version.source_id)}`}
                    className={`rounded border px-2 py-1 ${version.id === gallery.id ? 'border-vault-accent text-vault-accent' : 'border-vault-border text-vault-text-secondary'}`}
                  >
                    {version.title || `#${version.id}`}
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {upscaleOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="upscale-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !upscaleSubmitting) setUpscaleOpen(false)
          }}
        >
          <div className="w-full max-w-md rounded-xl border border-vault-border bg-vault-card p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 id="upscale-title" className="flex items-center gap-2 text-lg font-semibold">
                <Sparkles size={18} className="text-purple-300" />
                {t('library.aiUpscale')}
              </h2>
              <button
                type="button"
                aria-label={t('common.close')}
                disabled={upscaleSubmitting}
                onClick={() => setUpscaleOpen(false)}
                className="rounded p-1 text-vault-text-muted hover:text-vault-text disabled:opacity-50"
              >
                <X size={18} />
              </button>
            </div>
            <div className="space-y-4">
              <label className="block text-sm text-vault-text-secondary">
                {t('library.aiUpscaleImage')}
                <select
                  value={upscaleImageId ?? ''}
                  onChange={(event) => setUpscaleImageId(Number(event.target.value))}
                  className="mt-1.5 w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
                >
                  {images.map((image) => (
                    <option key={image.id} value={image.id}>
                      {image.filename || `${t('library.metaPages')} ${image.page_num}`}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm text-vault-text-secondary">
                {t('library.aiUpscaleModel')}
                <select
                  value={upscaleModel}
                  onChange={(event) => setUpscaleModel(event.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
                >
                  <option value="">{t('library.aiUpscaleDefaultModel')}</option>
                  {(pluginHealth?.services.swarmui?.models ?? []).map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm text-vault-text-secondary">
                {t('library.aiUpscaleScale')}
                <select
                  value={upscaleScale}
                  onChange={(event) => setUpscaleScale(Number(event.target.value))}
                  className="mt-1.5 w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-vault-text"
                >
                  {[1.5, 2, 3, 4].map((scale) => (
                    <option key={scale} value={scale}>
                      {scale}×
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                disabled={
                  !upscaleImageId ||
                  upscaleSubmitting ||
                  pluginHealthLoading ||
                  !pluginHealth?.services.swarmui?.online
                }
                onClick={async () => {
                  if (!upscaleImageId) return
                  setUpscaleSubmitting(true)
                  try {
                    await api.processing.processImage(upscaleImageId, {
                      processor_id: 'swarmui',
                      model: upscaleModel,
                      scale: upscaleScale,
                    })
                    toast.success(t('library.aiUpscaleQueued'))
                    setUpscaleOpen(false)
                  } catch (error) {
                    toast.error(error instanceof Error ? error.message : t('common.error'))
                  } finally {
                    setUpscaleSubmitting(false)
                  }
                }}
                className="w-full rounded-lg bg-purple-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-purple-500 disabled:opacity-50"
              >
                {upscaleSubmitting ? t('common.loading') : t('library.aiUpscaleStart')}
              </button>
            </div>
          </div>
        </div>
      )}

      {isCheckingUpdate && (
        <p className="text-xs text-vault-text-muted animate-pulse mb-2">
          {t('library.checkingMetadata')}
        </p>
      )}

      {activeJobId && gallery.download_status !== 'downloading' && (
        <div className="bg-vault-accent/10 border border-vault-accent/30 rounded-lg p-3 mb-5 flex items-center gap-2 text-vault-accent text-sm">
          <span className="flex gap-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-vault-accent animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-vault-accent animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-vault-accent animate-bounce [animation-delay:300ms]" />
          </span>
          {t('library.checkingForUpdates')}
        </div>
      )}

      {gallery.download_status === 'downloading' && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 mb-5 flex items-center gap-2 text-blue-400 text-sm">
          <span className="flex gap-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce [animation-delay:300ms]" />
          </span>
          {t('library.downloadingBanner')}
        </div>
      )}

      <GalleryTagSection
        source={gallery.source}
        tags={gallery.tags_array}
        translations={tagTranslations}
        tagData={tagData}
        onUpdateTag={handleUpdateTag}
      />

      {/* Image Thumbnails */}
      <div className="bg-vault-card border border-vault-border rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">
            {t('library.images')} ({gallery.pages} {t('library.metaPages')})
          </h2>
          <div className="flex items-center gap-2">
            {selectMode ? (
              <>
                <button
                  onClick={async () => {
                    const ids = [...selectedIds].slice(0, 6)
                    if (!ids.length) return
                    try {
                      const result = await api.saucenao.batch(ids, true, 80)
                      const applied = result.results.filter((item) => item.source_applied).length
                      toast.success(t('library.sourceLookupComplete', { count: applied }))
                      await mutateGallery()
                    } catch (error) {
                      toast.error(error instanceof Error ? error.message : String(error))
                    }
                  }}
                  disabled={selectedIds.size === 0 || selectedIds.size > 6}
                  title={t('library.sourceLookupLimit')}
                  className="px-3 py-1 rounded text-xs font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text transition-colors disabled:opacity-50"
                >
                  {t('library.findSources', { count: selectedIds.size })}
                </button>
                <button
                  onClick={handleHideSelected}
                  disabled={selectedIds.size === 0 || isHiding}
                  className="px-3 py-1 rounded text-xs font-medium border bg-red-900/30 border-red-700/50 text-red-400 hover:bg-red-900/50 transition-colors disabled:opacity-50"
                >
                  {isHiding
                    ? t('library.hidingImages')
                    : t('library.hideSelected', { count: selectedIds.size })}
                </button>
                <button
                  onClick={selectAllLoaded}
                  className="px-3 py-1 rounded text-xs font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text transition-colors"
                >
                  {t('library.selectAll')}
                </button>
                <button
                  onClick={invertSelection}
                  className="px-3 py-1 rounded text-xs font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text transition-colors"
                >
                  {t('library.invertSelection')}
                </button>
                <button
                  onClick={exitSelectMode}
                  className="px-3 py-1 rounded text-xs font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text transition-colors"
                >
                  {t('library.cancelSelect')}
                </button>
              </>
            ) : (
              <>
                {images.length > 0 && (
                  <button
                    onClick={() => setSelectMode(true)}
                    className="px-3 py-1 rounded text-xs font-medium border bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text transition-colors"
                  >
                    {t('library.selectImages')}
                  </button>
                )}
                {(hiddenImages.length > 0 || excludedBlobs.length > 0) && (
                  <button
                    onClick={() => setShowExcluded(!showExcluded)}
                    className="px-3 py-1 rounded text-xs font-medium border bg-yellow-900/30 border-yellow-700/50 text-yellow-400 hover:bg-yellow-900/50 transition-colors"
                  >
                    {showExcluded
                      ? t('library.hideExcluded')
                      : t('library.showExcluded', {
                          count: hiddenImages.length + excludedBlobs.length,
                        })}
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {imagesLoading && (
          <div className="flex justify-center py-10">
            <LoadingSpinner />
          </div>
        )}

        {!imagesLoading && (
          <>
            <VirtualGrid
              items={images}
              columns={{ base: 4, sm: 6, md: 8, lg: 10 }}
              gap={8}
              estimateHeight={180}
              overscan={4}
              onLoadMore={loadMoreImages}
              hasMore={!imagesReachingEnd}
              isLoading={imagesLoadingMore}
              renderItem={(image, idx) => {
                const isSelected = selectedIds.has(image.id)
                if (selectMode) {
                  return (
                    <button
                      key={image.id}
                      type="button"
                      onClick={(e) => {
                        if (e.shiftKey) rangeSelectTo(idx)
                        else toggleSelect(image, idx)
                      }}
                      onTouchStart={(e) => {
                        selectLpTargetRef.current = idx
                        selLpStart(e)
                      }}
                      onTouchMove={selLpMove}
                      onTouchEnd={selLpEnd}
                      onContextMenu={(e) => {
                        selectLpTargetRef.current = idx
                        selLpCtx(e)
                      }}
                      className={`relative group rounded border-2 transition-colors select-none [-webkit-touch-callout:none] ${
                        isSelected
                          ? 'border-red-500 ring-2 ring-red-500/30'
                          : 'border-vault-border hover:border-vault-border-hover'
                      }`}
                    >
                      {image.thumb_path ? (
                        <AppImage
                          src={image.thumb_path}
                          alt={`Page ${image.page_num}`}
                          loading={idx < 20 ? undefined : 'lazy'}
                          className={`w-full aspect-[3/4] object-cover rounded ${isSelected ? 'opacity-60' : ''}`}
                        />
                      ) : (
                        <div className="w-full aspect-[3/4] bg-vault-input rounded flex items-center justify-center text-vault-text-muted text-xs">
                          {image.page_num}
                        </div>
                      )}
                      {isSelected && (
                        <div className="absolute top-1 right-1 w-5 h-5 bg-red-500 rounded-full flex items-center justify-center">
                          <svg
                            className="w-3 h-3 text-white"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={3}
                              d="M5 13l4 4L19 7"
                            />
                          </svg>
                        </div>
                      )}
                    </button>
                  )
                }
                return (
                  <div
                    key={image.id}
                    role="button"
                    tabIndex={0}
                    onClick={() =>
                      router.push(readerHref(gallery.source, gallery.source_id, image.page_num))
                    }
                    onKeyDown={(e) => {
                      if (e.key === 'Enter')
                        router.push(readerHref(gallery.source, gallery.source_id, image.page_num))
                    }}
                    onTouchStart={(e) => {
                      activeImageRef.current = image
                      lpStart(e)
                    }}
                    onTouchMove={lpMove}
                    onTouchEnd={lpEnd}
                    onContextMenu={(e) => {
                      activeImageRef.current = image
                      lpCtx(e)
                    }}
                    className="group relative cursor-pointer select-none [-webkit-touch-callout:none]"
                  >
                    {image.thumb_path ? (
                      <AppImage
                        src={image.thumb_path}
                        alt={`Page ${image.page_num}`}
                        loading={idx < 20 ? undefined : 'lazy'}
                        className="w-full aspect-[3/4] object-cover rounded border border-vault-border group-hover:border-vault-border-hover transition-colors"
                      />
                    ) : (
                      <div className="w-full aspect-[3/4] bg-vault-input rounded border border-vault-border group-hover:border-vault-border-hover flex items-center justify-center text-vault-text-muted text-xs transition-colors">
                        {image.page_num}
                      </div>
                    )}
                    {isFavorited(image.id) && (
                      <div className="absolute top-1 right-1">
                        <Heart className="w-4 h-4 fill-current text-red-400 drop-shadow" />
                      </div>
                    )}
                    {imageMenu?.imageId === image.id && (
                      <div className="absolute inset-0 rounded border-2 border-vault-accent pointer-events-none" />
                    )}
                  </div>
                )
              }}
            />

            {images.length === 0 && (
              <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2">
                {Array.from({ length: Math.min(gallery.pages, 40) }).map((_, i) => (
                  <Link
                    key={i}
                    href={readerHref(gallery.source, gallery.source_id, i + 1)}
                    className="w-full aspect-[3/4] bg-vault-input rounded border border-vault-border hover:border-vault-border-hover flex items-center justify-center text-vault-text-muted text-xs transition-colors"
                  >
                    {i + 1}
                  </Link>
                ))}
              </div>
            )}
          </>
        )}

        {/* Hidden and excluded images panel */}
        {showExcluded && (hiddenImages.length > 0 || excludedBlobs.length > 0) && (
          <div className="mt-4 pt-4 border-t border-vault-border">
            <h3 className="text-sm font-semibold text-yellow-400 mb-3">
              {t('library.excludedImages')} ({hiddenImages.length + excludedBlobs.length})
            </h3>
            <div className="space-y-2">
              {hiddenImages.map((image) => (
                <div
                  key={image.id}
                  className="flex items-center justify-between bg-vault-input border border-vault-border rounded px-3 py-2"
                >
                  <div className="flex items-center gap-3 min-w-0 mr-3">
                    {image.thumb_path && (
                      <AppImage
                        src={image.thumb_path}
                        alt=""
                        className="h-12 w-9 object-cover rounded border border-vault-border"
                        sizes="36px"
                      />
                    )}
                    <div className="flex flex-col min-w-0">
                      <span className="text-xs text-vault-text-muted truncate">
                        {image.filename || `Page ${image.source_position ?? image.page_num}`}
                      </span>
                      {image.hidden_at && (
                        <span className="text-[10px] text-vault-text-muted">
                          {formatDate(image.hidden_at)}
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => handleRestoreImage(image.id)}
                    disabled={restoringImageId === image.id}
                    className="px-3 py-1 rounded text-xs font-medium border bg-green-900/30 border-green-700/50 text-green-400 hover:bg-green-900/50 transition-colors disabled:opacity-50 shrink-0"
                  >
                    {restoringImageId === image.id ? '...' : t('library.restoreHidden')}
                  </button>
                </div>
              ))}
              {excludedBlobs.map((blob) => (
                <div
                  key={blob.blob_sha256}
                  className="flex items-center justify-between bg-vault-input border border-vault-border rounded px-3 py-2"
                >
                  <div className="flex flex-col min-w-0 mr-3">
                    <span className="text-xs text-vault-text-muted font-mono truncate">
                      {blob.blob_sha256.slice(0, 16)}...
                    </span>
                    {blob.excluded_at && (
                      <span className="text-[10px] text-vault-text-muted">
                        {formatDate(blob.excluded_at)}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => handleRestore(blob.blob_sha256)}
                    disabled={restoringHash === blob.blob_sha256}
                    className="px-3 py-1 rounded text-xs font-medium border bg-green-900/30 border-green-700/50 text-green-400 hover:bg-green-900/50 transition-colors disabled:opacity-50 shrink-0"
                  >
                    {restoringHash === blob.blob_sha256 ? '...' : t('library.restoreExcluded')}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {imageMenu?.open && (
        <ImageContextMenu
          open={true}
          onClose={() => setImageMenu(null)}
          position={imageMenu.position}
          imageUrl={imageMenu.imageUrl}
          imageName={imageMenu.imageName}
          onHide={handleImageHide}
          onSelect={() => enterSelectModeWith(imageMenu.imageId)}
          isFavorited={isFavorited(imageMenu.imageId)}
          onToggleFavorite={handleImageToggleFavorite}
          onFindSimilar={() => {
            setSimilarImageId(imageMenu.imageId)
            setImageMenu(null)
          }}
          onFindSource={() => {
            setSaucenaoImageId(imageMenu.imageId)
            setImageMenu(null)
          }}
        />
      )}

      {similarImageId && (
        <SimilarImagesPanel imageId={similarImageId} onClose={() => setSimilarImageId(null)} />
      )}

      {saucenaoImageId && (
        <LazySauceNaoModal imageId={saucenaoImageId} onClose={() => setSaucenaoImageId(null)} />
      )}
    </div>
  )
}
