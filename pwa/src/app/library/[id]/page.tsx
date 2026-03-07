'use client'

import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useLibraryGallery, useGalleryImages, useUpdateGallery } from '@/hooks/useGalleries'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { TagBadge } from '@/components/TagBadge'
import { RatingStars } from '@/components/RatingStars'
import { t } from '@/lib/i18n'

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

const DOWNLOAD_STATUS_LABELS: Record<string, { label: string; className: string }> = {
  complete: { label: 'Complete', className: 'bg-green-900/40 border-green-700/50 text-green-400' },
  partial: { label: 'Partial', className: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-400' },
  proxy_only: { label: 'Proxy Only', className: 'bg-gray-800 border-gray-600 text-gray-400' },
}

export default function GalleryDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params?.id ? Number(params.id) : null

  const { data: gallery, isLoading: galleryLoading, error: galleryError, mutate: mutateGallery } = useLibraryGallery(id)
  const { data: imagesData, isLoading: imagesLoading } = useGalleryImages(id)
  const { trigger: updateGallery, isMutating: isUpdating } = useUpdateGallery(id ?? 0)

  const handleFavoriteToggle = async () => {
    if (!gallery) return
    try {
      const updated = await updateGallery({ favorited: !gallery.favorited })
      if (updated) mutateGallery(updated, false)
    } catch {
      // silently fail
    }
  }

  const handleRatingChange = async (newRating: number) => {
    if (!gallery) return
    try {
      const updated = await updateGallery({ rating: newRating })
      if (updated) mutateGallery(updated, false)
    } catch {
      // silently fail
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
  const images = imagesData?.images ?? []
  const statusInfo = DOWNLOAD_STATUS_LABELS[gallery.download_status] ?? DOWNLOAD_STATUS_LABELS.proxy_only

  return (
    <div className="min-h-screen bg-vault-bg text-vault-text">
      <div className="max-w-6xl mx-auto px-4 py-6">
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
                <h1 className="text-xl font-bold text-vault-text leading-tight">{gallery.title}</h1>
                <span className={`flex-shrink-0 px-2 py-0.5 rounded border text-xs font-medium ${statusInfo.className}`}>
                  {statusInfo.label}
                </span>
              </div>
              {gallery.title_jpn && (
                <p className="text-sm text-vault-text-secondary mb-3">{gallery.title_jpn}</p>
              )}

              {/* Meta grid */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 text-sm mb-4">
                {[
                  { label: 'Source', value: gallery.source },
                  { label: 'Category', value: gallery.category },
                  { label: 'Language', value: gallery.language || 'N/A' },
                  { label: 'Uploader', value: gallery.uploader || 'N/A' },
                  { label: 'Pages', value: String(gallery.pages) },
                  {
                    label: 'Added',
                    value: new Date(gallery.added_at).toLocaleDateString(),
                  },
                  ...(gallery.posted_at
                    ? [{ label: 'Posted', value: new Date(gallery.posted_at).toLocaleDateString() }]
                    : []),
                ].map(({ label, value }) => (
                  <div key={label}>
                    <span className="text-vault-text-muted">{label}: </span>
                    <span className="text-vault-text">{value}</span>
                  </div>
                ))}
              </div>

              {/* Rating */}
              <div className="flex items-center gap-3 mb-4">
                <span className="text-sm text-vault-text-muted">Rating:</span>
                <RatingStars
                  rating={gallery.rating}
                  readonly={false}
                  onChange={handleRatingChange}
                />
                <span className="text-sm text-vault-text-secondary">{gallery.rating.toFixed(1)}</span>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                <Link
                  href={`/reader/${gallery.id}`}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-medium transition-colors"
                >
                  {t('browse.read')}
                </Link>
                <button
                  onClick={handleFavoriteToggle}
                  disabled={isUpdating}
                  className={`px-4 py-2 rounded text-sm font-medium border transition-colors ${
                    gallery.favorited
                      ? 'bg-yellow-900/40 border-yellow-600 text-yellow-400 hover:bg-yellow-900/60'
                      : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-yellow-600 hover:text-yellow-400'
                  }`}
                >
                  {gallery.favorited ? '★ Favorited' : '☆ Favorite'}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Tags */}
        <div className="bg-vault-card border border-vault-border rounded-xl p-5 mb-5">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide mb-3">{t('common.tags')}</h2>
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
        </div>

        {/* Image Thumbnails */}
        <div className="bg-vault-card border border-vault-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide mb-3">
            {t('library.images')} ({gallery.pages} pages)
          </h2>

          {imagesLoading && (
            <div className="flex justify-center py-10">
              <LoadingSpinner />
            </div>
          )}

          {!imagesLoading && (
            <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2">
              {images.map((image) => (
                <Link
                  key={image.id}
                  href={`/reader/${gallery.id}?page=${image.page_num}`}
                  className="group"
                >
                  {image.thumb_path ? (
                    <img
                      src={image.thumb_path}
                      alt={`Page ${image.page_num}`}
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
    </div>
  )
}
