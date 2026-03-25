'use client'

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { toast } from 'sonner'
import useSWR from 'swr'
import { useLibraryGallery, useGalleryImages, useUpdateGallery } from '@/hooks/useGalleries'
import { useTagTranslations } from '@/hooks/useTagTranslations'
import { api } from '@/lib/api'
import type { GalleryImage } from '@/lib/types'
import { ImageContextMenu } from '@/components/Reader/ImageContextMenu'
import { useLongPress } from '@/hooks/useLongPress'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { RatingStars } from '@/components/RatingStars'
import { t, formatDate } from '@/lib/i18n'
import { BackButton } from '@/components/BackButton'
import { TagAutocomplete } from '@/components/TagAutocomplete'
import { Pencil, Heart, Bookmark, BookmarkCheck } from 'lucide-react'
import { SimilarImagesPanel } from '@/components/SimilarImagesPanel'
import { SauceNaoModal } from '@/components/SauceNaoModal'
import { TagSearchPopover } from '@/components/TagSearchPopover'

const TAG_NAMESPACE_COLORS: Record<string, string> = {
  character: 'bg-purple-900/40 border-purple-700/50 text-purple-300',
  artist: 'bg-orange-900/40 border-orange-700/50 text-orange-300',
  parody: 'bg-blue-900/40 border-blue-700/50 text-blue-300',
  group: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-300',
  language: 'bg-teal-900/40 border-teal-700/50 text-teal-300',
  male: 'bg-cyan-900/40 border-cyan-700/50 text-cyan-300',
  female: 'bg-pink-900/40 border-pink-700/50 text-pink-300',
  general: 'bg-vault-input border-vault-border text-vault-text-secondary',
}

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

function getTagColor(tag: string): string {
  const ns = tag.split(':')[0]
  return TAG_NAMESPACE_COLORS[ns] ?? TAG_NAMESPACE_COLORS.general
}

function groupTagsByNamespace(tags: string[]): Record<string, string[]> {
  const groups: Record<string, string[]> = {}
  for (const tag of tags) {
    const [ns, ...rest] = tag.split(':')
    const namespace = rest.length > 0 ? ns : 'general'
    const value = rest.length > 0 ? rest.join(':') : tag
    if (!groups[namespace]) groups[namespace] = []
    groups[namespace].push(value)
  }
  return groups
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
  const source = params?.source ?? null
  const sourceId = params?.sourceId ?? null

  const {
    data: gallery,
    isLoading: galleryLoading,
    error: galleryError,
    mutate: mutateGallery,
  } = useLibraryGallery(source, sourceId)
  const {
    data: imagesData,
    isLoading: imagesLoading,
    mutate: mutateImages,
  } = useGalleryImages(source, sourceId)
  const { trigger: updateGallery, isMutating: isUpdating } = useUpdateGallery(
    source ?? '',
    sourceId ?? '',
  )
  const { data: tagTranslations } = useTagTranslations(gallery?.tags_array ?? [])
  const { data: featureSettings } = useSWR('settings/features', () => api.settings.getFeatures(), {
    revalidateOnFocus: false,
    dedupingInterval: 300000, // 5 min cache
  })
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false)
  const [pagesOutdated, setPagesOutdated] = useState<{ old: number; new: number } | null>(null)
  const updateCheckedRef = useRef<boolean>(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isRetagging, setIsRetagging] = useState(false)
  const [tagData, setTagData] = useState<
    Array<{ namespace: string; name: string; confidence: number; source: string }>
  >([])
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.35)
  const [editingTags, setEditingTags] = useState(false)
  const [tagPopover, setTagPopover] = useState<{
    anchor: HTMLElement
    tag: string
    source: string
  } | null>(null)

  // Image multi-select & exclusion state
  const [selectMode, setSelectMode] = useState(false)
  const [selectedPages, setSelectedPages] = useState<Set<number>>(new Set())
  const [isHiding, setIsHiding] = useState(false)
  const [excludedBlobs, setExcludedBlobs] = useState<
    Array<{ blob_sha256: string; excluded_at: string | null }>
  >([])
  const [showExcluded, setShowExcluded] = useState(false)
  const [restoringHash, setRestoringHash] = useState<string | null>(null)

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
    // Only EH galleries support metadata check
    if (gallery.source !== 'ehentai') {
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
          router.push(`/reader/${gallery.source}/${gallery.source_id}`)
        }
      }
      if (e.key === 'ArrowUp' || e.key === 'Escape') {
        e.preventDefault()
        history.length > 1 ? router.back() : router.push('/library')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [gallery?.source, gallery?.source_id, router, selectMode])

  const isDownloading = gallery?.download_status === 'downloading'
  useEffect(() => {
    if (!isDownloading) return
    const interval = setInterval(() => {
      mutateGallery()
      mutateImages()
    }, 5000)
    return () => clearInterval(interval)
  }, [isDownloading, mutateGallery, mutateImages])

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

  // Toggle image selection
  const togglePage = (pageNum: number) => {
    setSelectedPages((prev) => {
      const next = new Set(prev)
      if (next.has(pageNum)) next.delete(pageNum)
      else next.add(pageNum)
      return next
    })
  }

  // Batch hide selected images
  const handleHideSelected = async () => {
    if (!source || !sourceId || selectedPages.size === 0) return
    if (!confirm(t('library.hideSelectedConfirm', { count: selectedPages.size }))) return
    setIsHiding(true)
    let hidden = 0
    try {
      // Delete one by one (page numbers shift after each delete, so sort descending)
      const sorted = [...selectedPages].sort((a, b) => b - a)
      for (const pageNum of sorted) {
        try {
          await api.library.deleteImage(source, sourceId, pageNum)
          hidden++
        } catch {
          toast.error(t('library.hideImageFailed'))
        }
      }
      if (hidden > 0) {
        toast.success(t('library.imagesHidden', { count: hidden }))
        mutateGallery()
        mutateImages()
      }
    } finally {
      setSelectedPages(new Set())
      setSelectMode(false)
      setIsHiding(false)
      fetchExcluded()
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

  useEffect(() => {
    fetchExcluded()
  }, [fetchExcluded])

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
      mutateImages(
        (prev) => {
          if (!prev) return prev
          return {
            ...prev,
            favorited_image_ids: wasFavorited
              ? (prev.favorited_image_ids ?? []).filter((id: number) => id !== imageId)
              : [...(prev.favorited_image_ids ?? []), imageId],
          }
        },
        { revalidate: false },
      )
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
    const { pageNum } = imageMenu
    setImageMenu(null)

    if (!window.confirm(t('reader.hideImageConfirm'))) return

    try {
      await api.library.deleteImage(source, sourceId, pageNum)
      toast.success(t('reader.imageHidden'))
      mutateGallery()
      mutateImages()
      fetchExcluded()
    } catch {
      toast.error(t('common.error'))
    }
  }, [imageMenu, source, sourceId, mutateGallery, mutateImages, fetchExcluded])

  const manualTagSet = useMemo(
    () =>
      new Set(
        tagData.filter((td) => td.source === 'manual').map((td) => `${td.namespace}:${td.name}`),
      ),
    [tagData],
  )

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

  const tagGroups = groupTagsByNamespace(gallery.tags_array)
  const aiTags = tagData.filter(
    (tag) => tag.source === 'ai' && tag.confidence >= confidenceThreshold,
  )
  const images = imagesData?.images ?? []
  const statusInfo =
    DOWNLOAD_STATUS_LABELS[gallery.download_status] ?? DOWNLOAD_STATUS_LABELS.proxy_only

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
              <img
                src={images[0].thumb_path}
                alt={gallery.title}
                className="w-40 h-56 object-cover rounded"
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
                <span className="shrink-0 px-2 py-0.5 rounded border text-xs font-medium bg-orange-900/40 border-orange-700/50 text-orange-400">
                  {t('library.statusOutdated')}
                </span>
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
              {/* Uploader — clickable when artist_id is available */}
              <div>
                <span className="text-vault-text-muted">{t('library.metaUploader')}: </span>
                {gallery.artist_id ? (
                  <Link
                    href={`/library?artist=${encodeURIComponent(gallery.artist_id)}`}
                    className="text-vault-text hover:text-vault-accent hover:underline transition-colors"
                  >
                    {gallery.uploader || 'N/A'}
                  </Link>
                ) : (
                  <span className="text-vault-text">{gallery.uploader || 'N/A'}</span>
                )}
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
                href={`/reader/${gallery.source}/${gallery.source_id}`}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-medium transition-colors"
              >
                {t('browse.read')}
              </Link>
              {gallery.artist_id && (
                <Link
                  href={`/library?artist=${encodeURIComponent(gallery.artist_id)}`}
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
            </div>
          </div>
        </div>
      </div>

      {isCheckingUpdate && (
        <p className="text-xs text-vault-text-muted animate-pulse mb-2">
          {t('library.checkingMetadata')}
        </p>
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

      {/* Tags */}
      <div className="bg-vault-card border border-vault-border rounded-xl p-5 mb-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">
            {t('common.tags')}
          </h2>
          <button
            onClick={() => setEditingTags(!editingTags)}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium border transition-colors ${
              editingTags
                ? 'bg-vault-accent/20 border-vault-accent text-vault-accent'
                : 'bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            <Pencil size={12} />
            {editingTags ? t('library.doneEditingTags') : t('library.editTags')}
          </button>
        </div>
        {editingTags && (
          <div className="mb-3">
            <TagAutocomplete
              onSelect={(tag) => handleUpdateTag(tag, 'add')}
              clearOnSelect={true}
              placeholder={t('library.addTagPlaceholder')}
            />
          </div>
        )}
        {Object.keys(tagGroups).length === 0 ? (
          <p className="text-sm text-vault-text-muted">{t('library.noTags')}</p>
        ) : (
          <div className="space-y-2">
            {Object.entries(tagGroups).map(([namespace, values]) => (
              <div key={namespace} className="flex flex-wrap gap-1 items-start">
                <span className="text-xs text-vault-text-muted w-20 shrink-0 pt-0.5 capitalize">
                  {namespace}:
                </span>
                <div className="flex flex-wrap gap-1">
                  {values.map((value) => {
                    const fullTag = namespace === 'general' ? value : `${namespace}:${value}`
                    const translation = tagTranslations?.[fullTag]
                    const isManual = manualTagSet.has(fullTag)
                    return (
                      <span
                        key={value}
                        role="button"
                        tabIndex={0}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs cursor-pointer hover:brightness-125 ${getTagColor(fullTag)}`}
                        title={translation ? `${namespace}:${value}` : undefined}
                        onClick={(e) => {
                          if (editingTags) return
                          const src = gallery?.source ?? ''
                          if (src === 'local' || (src !== 'ehentai' && src !== 'pixiv')) {
                            const bare = fullTag.includes(':')
                              ? fullTag.split(':').slice(1).join(':')
                              : fullTag
                            router.push(`/library?q=${encodeURIComponent(bare)}`)
                          } else {
                            setTagPopover({ anchor: e.currentTarget, tag: fullTag, source: src })
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            const src = gallery?.source ?? ''
                            if (src === 'local' || (src !== 'ehentai' && src !== 'pixiv')) {
                              const bare = fullTag.includes(':')
                                ? fullTag.split(':').slice(1).join(':')
                                : fullTag
                              router.push(`/library?q=${encodeURIComponent(bare)}`)
                            } else {
                              setTagPopover({
                                anchor: e.currentTarget,
                                tag: fullTag,
                                source: src,
                              })
                            }
                          }
                        }}
                      >
                        {translation || value}
                        {editingTags && isManual && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleUpdateTag(fullTag, 'remove')
                            }}
                            className="ml-0.5 opacity-60 hover:opacity-100 leading-none"
                            aria-label={t('common.removeTag', { tag: fullTag })}
                          >
                            ×
                          </button>
                        )}
                      </span>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* AI Tags (if any) */}
        {tagData.some((t) => t.source === 'ai') && (
          <div className="mt-4 pt-4 border-t border-vault-border">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-vault-text-secondary uppercase tracking-wide">
                {t('library.aiTags')}
              </h3>
              <div className="flex items-center gap-2">
                <label className="text-xs text-vault-text-muted">
                  {t('library.confidence')}: {Math.round(confidenceThreshold * 100)}%
                </label>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={Math.round(confidenceThreshold * 100)}
                  onChange={(e) => setConfidenceThreshold(Number(e.target.value) / 100)}
                  className="w-24 h-1.5 accent-purple-500"
                />
              </div>
            </div>
            {aiTags.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {aiTags.map((tag) => {
                  const aiFullTag =
                    tag.namespace === 'general' ? tag.name : `${tag.namespace}:${tag.name}`
                  return (
                    <span
                      key={`${tag.namespace}:${tag.name}`}
                      role="button"
                      tabIndex={0}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border bg-purple-900/30 border-purple-700/40 text-purple-300 text-xs cursor-pointer hover:brightness-125"
                      title={`${Math.round(tag.confidence * 100)}% confidence`}
                      onClick={(e) => {
                        const src = gallery?.source ?? ''
                        if (src === 'local' || (src !== 'ehentai' && src !== 'pixiv')) {
                          router.push(`/library?q=${encodeURIComponent(tag.name)}`)
                        } else {
                          setTagPopover({ anchor: e.currentTarget, tag: aiFullTag, source: src })
                        }
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          const src = gallery?.source ?? ''
                          if (src === 'local' || (src !== 'ehentai' && src !== 'pixiv')) {
                            router.push(`/library?q=${encodeURIComponent(tag.name)}`)
                          } else {
                            setTagPopover({
                              anchor: e.currentTarget,
                              tag: aiFullTag,
                              source: src,
                            })
                          }
                        }
                      }}
                    >
                      {tag.namespace !== 'general' && (
                        <span className="text-purple-400/60">{tag.namespace}:</span>
                      )}
                      {tag.name}
                      <span className="text-purple-400/50 text-[10px]">
                        {Math.round(tag.confidence * 100)}%
                      </span>
                    </span>
                  )
                })}
              </div>
            ) : (
              <p className="text-xs text-vault-text-muted">{t('library.noAiTagsAboveThreshold')}</p>
            )}
          </div>
        )}
        {tagPopover && (
          <TagSearchPopover
            tag={tagPopover.tag}
            gallerySource={tagPopover.source}
            anchorEl={tagPopover.anchor}
            onClose={() => setTagPopover(null)}
          />
        )}
      </div>

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
                  onClick={handleHideSelected}
                  disabled={selectedPages.size === 0 || isHiding}
                  className="px-3 py-1 rounded text-xs font-medium border bg-red-900/30 border-red-700/50 text-red-400 hover:bg-red-900/50 transition-colors disabled:opacity-50"
                >
                  {isHiding
                    ? t('library.hidingImages')
                    : t('library.hideSelected', { count: selectedPages.size })}
                </button>
                <button
                  onClick={() => {
                    setSelectMode(false)
                    setSelectedPages(new Set())
                  }}
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
                {excludedBlobs.length > 0 && (
                  <button
                    onClick={() => setShowExcluded(!showExcluded)}
                    className="px-3 py-1 rounded text-xs font-medium border bg-yellow-900/30 border-yellow-700/50 text-yellow-400 hover:bg-yellow-900/50 transition-colors"
                  >
                    {showExcluded
                      ? t('library.hideExcluded')
                      : t('library.showExcluded', { count: excludedBlobs.length })}
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
          <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2">
            {images.map((image, idx) => {
              const isSelected = selectedPages.has(image.page_num)
              if (selectMode) {
                return (
                  <button
                    key={image.id}
                    type="button"
                    onClick={() => togglePage(image.page_num)}
                    className={`relative group rounded border-2 transition-colors ${
                      isSelected
                        ? 'border-red-500 ring-2 ring-red-500/30'
                        : 'border-vault-border hover:border-vault-border-hover'
                    }`}
                  >
                    {image.thumb_path ? (
                      <img
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
                    router.push(
                      `/reader/${gallery.source}/${gallery.source_id}?page=${image.page_num}`,
                    )
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter')
                      router.push(
                        `/reader/${gallery.source}/${gallery.source_id}?page=${image.page_num}`,
                      )
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
                    <img
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
            })}

            {/* Placeholder pages if images array is shorter than pages count */}
            {images.length === 0 &&
              Array.from({ length: Math.min(gallery.pages, 40) }).map((_, i) => (
                <Link
                  key={i}
                  href={`/reader/${gallery.source}/${gallery.source_id}?page=${i + 1}`}
                  className="w-full aspect-[3/4] bg-vault-input rounded border border-vault-border hover:border-vault-border-hover flex items-center justify-center text-vault-text-muted text-xs transition-colors"
                >
                  {i + 1}
                </Link>
              ))}
          </div>
        )}

        {/* Excluded (hidden) images panel */}
        {showExcluded && excludedBlobs.length > 0 && (
          <div className="mt-4 pt-4 border-t border-vault-border">
            <h3 className="text-sm font-semibold text-yellow-400 mb-3">
              {t('library.excludedImages')} ({excludedBlobs.length})
            </h3>
            <div className="space-y-2">
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
        <SauceNaoModal imageId={saucenaoImageId} onClose={() => setSaucenaoImageId(null)} />
      )}
    </div>
  )
}
