'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Grid, Image as ImageIcon, BookOpen, Users, Heart, Download } from 'lucide-react'
import { BackButton } from '@/components/BackButton'
import { useArtistSummary, useArtistImages } from '@/hooks/useArtists'
import { useLibraryGalleries } from '@/hooks/useGalleries'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { Pagination } from '@/components/Pagination'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useFollowedArtists, useFollowArtist, useUnfollowArtist, usePatchFollow } from '@/hooks/useFollowedArtists'
import { toast } from 'sonner'

function getGalleryColCount() {
  if (typeof window === 'undefined') return 2
  const w = window.innerWidth
  if (w >= 1280) return 6
  if (w >= 1024) return 5
  if (w >= 768) return 4
  if (w >= 640) return 3
  return 2
}

type ViewTab = 'galleries' | 'images'

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  ehentai: 'bg-orange-500/20 text-orange-400',
  twitter: 'bg-sky-500/20 text-sky-400',
}

const GALLERY_PAGE_SIZE = 24
const IMAGE_PAGE_SIZE = 40

export default function ArtistDetailPage() {
  useLocale()
  const router = useRouter()
  const params = useParams()
  const rawArtistId = Array.isArray(params.artistId) ? params.artistId[0] : params.artistId
  const artistId = decodeURIComponent(rawArtistId ?? '')

  const [activeTab, setActiveTab] = useState<ViewTab>('galleries')
  const [galleryPage, setGalleryPage] = useState(0)
  const [imagePage, setImagePage] = useState(0)
  const [imageSort, setImageSort] = useState<'newest' | 'oldest'>('newest')
  const [colCount, setColCount] = useState(getGalleryColCount)

  useEffect(() => {
    const handler = () => setColCount(getGalleryColCount())
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  const { data: summary, isLoading: summaryLoading } = useArtistSummary(artistId)

  const { data: followedData } = useFollowedArtists()
  const { trigger: followArtist, isMutating: isFollowing } = useFollowArtist()
  const { trigger: unfollowArtist, isMutating: isUnfollowing } = useUnfollowArtist()
  const { trigger: patchFollow } = usePatchFollow()

  const followEntry = followedData?.artists?.find((a) => a.artist_id === artistId)
  const isFollowed = !!followEntry

  const {
    data: galleriesData,
    isLoading: galleriesLoading,
    isValidating: galleriesValidating,
  } = useLibraryGalleries({
    artist: artistId,
    page: galleryPage,
    limit: GALLERY_PAGE_SIZE,
  })

  const galleries = galleriesData?.galleries ?? []
  const { focusedIndex } = useGridKeyboard({
    totalItems: galleries.length,
    colCount,
    onEnter: (i) => {
      const g = galleries[i]
      if (g) router.push(`/library/${g.source}/${g.source_id}`)
    },
    enabled: activeTab === 'galleries',
  })

  const {
    data: imagesData,
    isLoading: imagesLoading,
    isValidating: imagesValidating,
  } = useArtistImages(artistId, {
    page: imagePage,
    limit: IMAGE_PAGE_SIZE,
    sort: imageSort,
  })

  const handleReadAll = () => {
    router.push(`/reader/artist/${encodeURIComponent(artistId)}`)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <BackButton fallback="/artists" />

        <div className="flex-1 min-w-0">
          {summaryLoading ? (
            <div className="h-8 w-48 bg-vault-card rounded animate-pulse" />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold text-vault-text truncate">
                {summary?.artist_name || artistId}
              </h1>
              {summary?.source && (
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${SOURCE_COLORS[summary.source] ?? 'bg-vault-text-secondary/20 text-vault-text-secondary'}`}
                >
                  {summary.source}
                </span>
              )}
            </div>
          )}

          {summary && (
            <p className="text-sm text-vault-text-secondary mt-1">
              {t('artists.galleryCount', { count: String(summary.gallery_count) })}
              {' · '}
              {t('artists.totalPages', { count: String(summary.total_pages) })}
              {' · '}
              {t('artists.totalImages', { count: String(summary.total_images) })}
            </p>
          )}
        </div>

        <button
          onClick={handleReadAll}
          className="flex items-center gap-2 px-4 py-2 bg-vault-accent hover:bg-vault-accent/80 text-white rounded-lg text-sm font-medium transition-colors shrink-0"
        >
          <BookOpen size={16} />
          {t('artists.readAll')}
        </button>

        {/* Follow/Unfollow button */}
        <button
          onClick={async () => {
            try {
              if (isFollowed) {
                await unfollowArtist({ artistId, source: followEntry?.source ?? 'local' })
                toast.success(t('artists.unfollowSuccess', { name: artistId }))
              } else {
                await followArtist({
                  source: summary?.source ?? 'local',
                  artist_id: artistId,
                  artist_name: summary?.artist_name ?? artistId,
                })
                toast.success(t('artists.followSuccess', { name: artistId }))
              }
            } catch {
              toast.error(t('common.error'))
            }
          }}
          disabled={isFollowing || isUnfollowing}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors shrink-0 ${
            isFollowed
              ? 'bg-vault-accent text-indigo-300 hover:bg-red-500/20 hover:text-red-400'
              : 'bg-indigo-600 text-white hover:bg-indigo-500'
          }`}
        >
          <Heart size={14} className={isFollowed ? 'fill-current' : ''} />
          {isFollowed ? t('artists.following') : t('artists.follow')}
        </button>

        {/* Auto-download toggle when followed */}
        {isFollowed && (
          <button
            onClick={async () => {
              try {
                await patchFollow({
                  artistId,
                  data: { auto_download: !followEntry.auto_download },
                  source: followEntry.source,
                })
                toast.success(
                  followEntry.auto_download
                    ? t('artists.autoDownloadOff')
                    : t('artists.autoDownloadOn'),
                )
              } catch {
                toast.error(t('common.error'))
              }
            }}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors shrink-0 ${
              followEntry.auto_download
                ? 'bg-green-500/20 text-green-400'
                : 'bg-vault-accent text-vault-text-muted'
            }`}
          >
            <Download size={12} />
            {t('artists.autoDownload')}
          </button>
        )}
      </div>

      {/* Tab Switcher */}
      <div className="flex gap-1 bg-vault-card border border-vault-border rounded-lg p-1 w-fit">
        <button
          onClick={() => setActiveTab('galleries')}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'galleries'
              ? 'bg-vault-accent text-white'
              : 'text-vault-text-secondary hover:text-vault-text'
          }`}
        >
          <Grid size={15} />
          {t('artists.viewGalleries')}
        </button>
        <button
          onClick={() => setActiveTab('images')}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'images'
              ? 'bg-vault-accent text-white'
              : 'text-vault-text-secondary hover:text-vault-text'
          }`}
        >
          <ImageIcon size={15} />
          {t('artists.viewImages')}
        </button>
      </div>

      {/* Galleries Tab */}
      {activeTab === 'galleries' && (
        <div className="space-y-4">
          {galleriesLoading ? (
            <div className="text-center py-12 text-vault-text-secondary">{t('common.loading')}</div>
          ) : !galleriesData?.galleries?.length ? (
            <div className="flex flex-col items-center py-16 gap-3 text-vault-text-secondary">
              <Users size={48} className="opacity-30" />
              <p>{t('library.noGalleries')}</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                {galleriesData.galleries.map((gallery, idx) => (
                  <button
                    key={gallery.id}
                    data-grid-index={idx}
                    onClick={() => router.push(`/library/${gallery.source}/${gallery.source_id}`)}
                    className="bg-vault-card border border-vault-border rounded-xl overflow-hidden hover:border-vault-accent/50 hover:shadow-lg transition-all text-left group focus:outline-none focus:ring-2 focus:ring-vault-accent"
                  >
                    <div className="aspect-[3/4] bg-vault-bg relative overflow-hidden">
                      {gallery.cover_thumb ? (
                        <img
                          src={gallery.cover_thumb}
                          alt={gallery.title}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <BookOpen size={32} className="text-vault-text-secondary/30" />
                        </div>
                      )}
                    </div>
                    <div className="p-2.5 space-y-1">
                      <p className="font-medium text-xs text-vault-text line-clamp-2 leading-snug">
                        {gallery.title || gallery.title_jpn}
                      </p>
                      <p className="text-xs text-vault-text-secondary">{gallery.pages}p</p>
                    </div>
                  </button>
                ))}
              </div>

              {galleriesData.total !== undefined && (
                <Pagination
                  page={galleryPage}
                  total={galleriesData.total}
                  pageSize={GALLERY_PAGE_SIZE}
                  onChange={(p) => setGalleryPage(p)}
                  isLoading={galleriesValidating}
                />
              )}
            </>
          )}
        </div>
      )}

      {/* Images Tab */}
      {activeTab === 'images' && (
        <div className="space-y-4">
          {/* Sort controls */}
          <div className="flex justify-end">
            <select
              value={imageSort}
              onChange={(e) => {
                setImageSort(e.target.value as 'newest' | 'oldest')
                setImagePage(0)
              }}
              className="px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text focus:outline-none focus:ring-1 focus:ring-vault-accent"
            >
              <option value="newest">{t('artists.sortNewest')}</option>
              <option value="oldest">{t('artists.sortOldest')}</option>
            </select>
          </div>

          {imagesLoading ? (
            <div className="text-center py-12 text-vault-text-secondary">{t('common.loading')}</div>
          ) : !imagesData?.images?.length ? (
            <div className="flex flex-col items-center py-16 gap-3 text-vault-text-secondary">
              <ImageIcon size={48} className="opacity-30" />
              <p>{t('artists.noImages')}</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-1.5">
                {imagesData.images.map((image, idx) => {
                  const globalIndex = imagePage * IMAGE_PAGE_SIZE + idx
                  return (
                    <button
                      key={image.id}
                      onClick={() =>
                        router.push(
                          `/reader/artist/${encodeURIComponent(artistId)}?start=${globalIndex}`,
                        )
                      }
                      className="aspect-square bg-vault-card border border-vault-border rounded-lg overflow-hidden hover:border-vault-accent/50 hover:shadow-md transition-all group relative"
                      title={t('artists.fromGallery', { title: image.gallery_title })}
                    >
                      {image.thumb_path ? (
                        <img
                          src={image.thumb_path}
                          alt={image.filename ?? ''}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <ImageIcon size={20} className="text-vault-text-secondary/30" />
                        </div>
                      )}
                      {/* Hover overlay with gallery title */}
                      <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-1.5">
                        <p className="text-white text-[10px] line-clamp-2 leading-tight">
                          {image.gallery_title}
                        </p>
                      </div>
                    </button>
                  )
                })}
              </div>

              {imagesData.total !== undefined && (
                <Pagination
                  page={imagePage}
                  total={imagesData.total}
                  pageSize={IMAGE_PAGE_SIZE}
                  onChange={(p) => setImagePage(p)}
                  isLoading={imagesValidating}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
