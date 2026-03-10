'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { toast } from 'sonner'
import { useLibraryGallery, useGalleryImages, useUpdateGallery } from '@/hooks/useGalleries'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { TagBadge } from '@/components/TagBadge'
import { RatingStars } from '@/components/RatingStars'
import { t, formatDate } from '@/lib/i18n'

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
}

export default function GalleryDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params?.id ? Number(params.id) : null

  const {
    data: gallery,
    isLoading: galleryLoading,
    error: galleryError,
    mutate: mutateGallery,
  } = useLibraryGallery(id)
  const { data: imagesData, isLoading: imagesLoading } = useGalleryImages(id)
  const { trigger: updateGallery, isMutating: isUpdating } = useUpdateGallery(id ?? 0)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isRetagging, setIsRetagging] = useState(false)
  const [tagData, setTagData] = useState<Array<{ namespace: string; name: string; confidence: number; source: string }>>([])
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.35)

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
            source: 'local',
            source_id: String(gallery.id),
            title: gallery.title,
            thumb: gallery.cover_thumb || undefined,
          })
          .catch(() => {})
      }
    } catch {
      // localStorage may be unavailable in some contexts
    }
  }, [gallery])

  useEffect(() => {
    if (!id) return
    api.library.getGalleryTags(id).then((res) => setTagData(res.tags)).catch(() => {})
  }, [id])

  const getDeleteConfirmKey = () => {
    if (gallery?.import_mode === 'link') return 'library.delete.link.confirm'
    if (gallery?.import_mode === 'copy') return 'library.delete.copy.confirm'
    return 'library.delete.download.confirm'
  }

  const handleDelete = async () => {
    if (!gallery || !id) return
    const confirmMsg = t(getDeleteConfirmKey(), { title: gallery.title })
    if (!confirm(confirmMsg)) return
    setIsDeleting(true)
    try {
      await api.library.deleteGallery(id)
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
    if (!id) return
    setIsRetagging(true)
    try {
      await api.tags.retag(id)
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
      const updated = await updateGallery({ favorited: !gallery.favorited })
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
  const aiTags = tagData.filter((tag) => tag.source === 'ai' && tag.confidence >= confidenceThreshold)
  const images = imagesData?.images ?? []
  const statusInfo =
    DOWNLOAD_STATUS_LABELS[gallery.download_status] ?? DOWNLOAD_STATUS_LABELS.proxy_only

  return (
    <div>
        {/* Back */}
        <button
          onClick={() => router.back()}
          className="text-sm text-vault-text-muted hover:text-vault-text-secondary mb-4 flex items-center gap-1 transition-colors"
        >
          {t('library.backToLibrary')}
        </button>

        {/* Header */}
        <div className="bg-vault-card border border-vault-border rounded-xl p-5 mb-5">
          <div className="flex flex-col md:flex-row gap-5">
            {/* Thumbnail preview from first image */}
            <div className="flex-shrink-0">
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
                    onClick={() => { setEditTitleValue(gallery.title); setEditingTitle(true) }}
                    className="text-xl font-bold text-vault-text leading-tight cursor-pointer hover:text-vault-accent transition-colors"
                    title={t('library.editTitle')}
                  >
                    {gallery.title}
                  </h1>
                )}
                <span
                  className={`flex-shrink-0 px-2 py-0.5 rounded border text-xs font-medium ${statusInfo.className}`}
                >
                  {t(statusInfo.labelKey)}
                </span>
              </div>
              {(gallery.title_jpn || editingTitleJpn) && (
                editingTitleJpn ? (
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
                    onClick={() => { setEditTitleJpnValue(gallery.title_jpn ?? ''); setEditingTitleJpn(true) }}
                    className="text-sm text-vault-text-secondary mb-3 cursor-pointer hover:text-vault-accent transition-colors"
                    title={t('library.editTitle')}
                  >
                    {gallery.title_jpn}
                  </p>
                )
              )}

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
                    {['Doujinshi', 'Manga', 'Artist CG', 'Game CG', 'Western', 'Non-H', 'Image Set', 'Cosplay', 'Asian Porn', 'Misc'].map((cat) => (
                      <option key={cat} value={cat}>{cat}</option>
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
                  rating={gallery.rating}
                  readonly={isUpdating}
                  onChange={handleRatingChange}
                />
                <span className="text-sm text-vault-text-secondary">
                  {gallery.rating.toFixed(1)}
                </span>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                <Link
                  href={`/reader/${gallery.id}`}
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
                <button
                  onClick={handleFavoriteToggle}
                  disabled={isUpdating}
                  className={`px-4 py-2 rounded text-sm font-medium border transition-colors ${
                    gallery.favorited
                      ? 'bg-yellow-900/40 border-yellow-600 text-yellow-400 hover:bg-yellow-900/60'
                      : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-yellow-600 hover:text-yellow-400'
                  }`}
                >
                  {gallery.favorited ? t('library.favorited') : t('library.unfavorited')}
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

        {/* Tags */}
        <div className="bg-vault-card border border-vault-border rounded-xl p-5 mb-5">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide mb-3">
            {t('common.tags')}
          </h2>
          {Object.keys(tagGroups).length === 0 ? (
            <p className="text-sm text-vault-text-muted">{t('library.noTags')}</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(tagGroups).map(([namespace, values]) => (
                <div key={namespace} className="flex flex-wrap gap-1 items-start">
                  <span className="text-xs text-vault-text-muted w-20 flex-shrink-0 pt-0.5 capitalize">
                    {namespace}:
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {values.map((value) => {
                      const fullTag = namespace === 'general' ? value : `${namespace}:${value}`
                      return (
                        <span
                          key={value}
                          className={`px-2 py-0.5 rounded border text-xs ${getTagColor(fullTag)}`}
                        >
                          {value}
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
                  {aiTags.map((tag) => (
                    <span
                      key={`${tag.namespace}:${tag.name}`}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded border bg-purple-900/30 border-purple-700/40 text-purple-300 text-xs"
                      title={`${Math.round(tag.confidence * 100)}% confidence`}
                    >
                      {tag.namespace !== 'general' && (
                        <span className="text-purple-400/60">{tag.namespace}:</span>
                      )}
                      {tag.name}
                      <span className="text-purple-400/50 text-[10px]">
                        {Math.round(tag.confidence * 100)}%
                      </span>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-vault-text-muted">{t('library.noAiTagsAboveThreshold')}</p>
              )}
            </div>
          )}
        </div>

        {/* Image Thumbnails */}
        <div className="bg-vault-card border border-vault-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide mb-3">
            {t('library.images')} ({gallery.pages} {t('library.metaPages')})
          </h2>

          {imagesLoading && (
            <div className="flex justify-center py-10">
              <LoadingSpinner />
            </div>
          )}

          {!imagesLoading && (
            <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2">
              {images.map((image, idx) => (
                <Link
                  key={image.id}
                  href={`/reader/${gallery.id}?page=${image.page_num}`}
                  className="group"
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
                </Link>
              ))}

              {/* Placeholder pages if images array is shorter than pages count */}
              {images.length === 0 &&
                Array.from({ length: Math.min(gallery.pages, 40) }).map((_, i) => (
                  <Link
                    key={i}
                    href={`/reader/${gallery.id}?page=${i + 1}`}
                    className="w-full aspect-[3/4] bg-vault-input rounded border border-vault-border hover:border-vault-border-hover flex items-center justify-center text-vault-text-muted text-xs transition-colors"
                  >
                    {i + 1}
                  </Link>
                ))}
            </div>
          )}
        </div>
    </div>
  )
}
