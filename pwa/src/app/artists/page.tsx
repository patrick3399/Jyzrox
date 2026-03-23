'use client'

import { useState, useMemo, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Users, RefreshCw } from 'lucide-react'
import { useArtists } from '@/hooks/useArtists'
import { Pagination } from '@/components/Pagination'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useScrollRestore } from '@/hooks/useScrollRestore'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { getSourceStyle } from '@/lib/galleryUtils'
import { useFollowedArtists, useCheckArtistUpdates } from '@/hooks/useFollowedArtists'
import { toast } from 'sonner'

// Column count inferred from CSS breakpoints:
// grid-cols-2 sm:4 md:5 lg:7 xl:8 2xl:10
function getColCount(): number {
  if (typeof window === 'undefined') return 2
  const w = window.innerWidth
  if (w >= 1536) return 10
  if (w >= 1280) return 8
  if (w >= 1024) return 7
  if (w >= 768) return 5
  if (w >= 640) return 4
  return 2
}

function ArtistsPageInner() {
  useLocale()
  const router = useRouter()
  const searchParams = useSearchParams()

  const [viewMode, setViewMode] = useState<'all' | 'followed'>('all')
  const { data: followedData, isLoading: followedLoading } = useFollowedArtists()
  const { trigger: checkUpdates, isMutating: isChecking } = useCheckArtistUpdates()

  const [query, setQuery] = useState(searchParams.get('q') ?? '')
  const [debouncedQuery, setDebouncedQuery] = useState(searchParams.get('q') ?? '')
  const [source, setSource] = useState(searchParams.get('source') ?? '')
  const [sort, setSort] = useState<'latest' | 'gallery_count' | 'total_pages'>(
    (searchParams.get('sort') as 'latest' | 'gallery_count' | 'total_pages') ?? 'latest',
  )
  const [page, setPage] = useState(Number(searchParams.get('page') ?? 0))
  const limit = 30

  // Derived col count for keyboard nav
  const [colCount, setColCount] = useState(getColCount)
  useEffect(() => {
    const onResize = () => setColCount(getColCount())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const debounceRef = useMemo(() => ({ timer: null as ReturnType<typeof setTimeout> | null }), [])
  const handleSearch = (val: string) => {
    setQuery(val)
    if (debounceRef.timer) clearTimeout(debounceRef.timer)
    debounceRef.timer = setTimeout(() => {
      setDebouncedQuery(val)
      setPage(0)
    }, 300)
  }

  const { data, isLoading, isValidating } = useArtists({
    q: debouncedQuery || undefined,
    source: source || undefined,
    sort,
    page,
    limit,
  })

  const artists = data?.artists ?? []

  // URL sync
  useEffect(() => {
    const params = new URLSearchParams()
    if (query) params.set('q', query)
    if (source) params.set('source', source)
    if (sort !== 'latest') params.set('sort', sort)
    if (page > 0) params.set('page', String(page))
    const qs = params.toString()
    router.replace(qs ? `/artists?${qs}` : '/artists', { scroll: false })
  }, [query, source, sort, page, router])

  // Scroll restoration
  const isReady = artists.length > 0
  const { saveScroll } = useScrollRestore('artists_scrollY', isReady)

  // Grid keyboard navigation
  const { focusedIndex } = useGridKeyboard({
    totalItems: artists.length,
    colCount,
    onEnter: (i) => {
      saveScroll()
      router.push(`/artists/${encodeURIComponent(artists[i].artist_id)}`)
    },
    enabled: artists.length > 0,
  })

  // Focus the card element when focusedIndex changes
  useEffect(() => {
    if (focusedIndex == null) return
    const el = document.querySelector<HTMLElement>(`[data-grid-index="${focusedIndex}"]`)
    el?.focus()
  }, [focusedIndex])

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-vault-text">{t('artists.title')}</h1>

      {/* View Mode Tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex gap-1 bg-vault-card border border-vault-border rounded-lg p-1">
          <button
            onClick={() => setViewMode('all')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              viewMode === 'all'
                ? 'bg-vault-accent text-white'
                : 'text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            {t('artists.viewAll')}
          </button>
          <button
            onClick={() => setViewMode('followed')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              viewMode === 'followed'
                ? 'bg-vault-accent text-white'
                : 'text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            {t('artists.viewFollowed')}
            {followedData?.artists?.length ? (
              <span className="ml-2 px-1.5 py-0.5 text-xs rounded-full bg-indigo-500/20 text-indigo-300">
                {followedData.artists.length}
              </span>
            ) : null}
          </button>
        </div>

        {viewMode === 'followed' && (
          <button
            onClick={async () => {
              try {
                await checkUpdates()
                toast.success(t('artists.updatesChecked'))
              } catch {
                toast.error(t('common.error'))
              }
            }}
            disabled={isChecking}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-vault-accent text-vault-text-muted hover:text-white text-sm transition-colors"
          >
            <RefreshCw size={14} className={isChecking ? 'animate-spin' : ''} />
            {isChecking ? t('artists.checkingUpdates') : t('artists.checkUpdates')}
          </button>
        )}
      </div>

      {viewMode === 'all' && (
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <input
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={t('artists.searchPlaceholder')}
              className="flex-1 min-w-[200px] px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder:text-vault-text-secondary focus:outline-none focus:ring-1 focus:ring-vault-accent"
            />
            <select
              value={source}
              onChange={(e) => {
                setSource(e.target.value)
                setPage(0)
              }}
              className="px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text focus:outline-none focus:ring-1 focus:ring-vault-accent"
            >
              <option value="">{t('common.all')}</option>
              <option value="pixiv">Pixiv</option>
              <option value="ehentai">E-Hentai</option>
              <option value="twitter">Twitter</option>
            </select>
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as typeof sort)
                setPage(0)
              }}
              className="px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text focus:outline-none focus:ring-1 focus:ring-vault-accent"
            >
              <option value="latest">{t('artists.sortLatest')}</option>
              <option value="gallery_count">{t('artists.sortGalleryCount')}</option>
              <option value="total_pages">{t('artists.sortTotalPages')}</option>
            </select>
          </div>

          {/* Grid */}
          {isLoading ? (
            <div className="text-center py-12 text-vault-text-secondary">{t('common.loading')}</div>
          ) : !artists.length ? (
            <div className="text-center py-12 text-vault-text-secondary">{t('artists.noArtists')}</div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-7 xl:grid-cols-8 2xl:grid-cols-10 gap-4">
              {artists.map((a, index) => (
                <button
                  key={a.artist_id}
                  data-grid-index={index}
                  tabIndex={0}
                  onClick={() => {
                    saveScroll()
                    router.push(`/artists/${encodeURIComponent(a.artist_id)}`)
                  }}
                  className="bg-vault-card border border-vault-border rounded-xl overflow-hidden hover:border-vault-accent/50 hover:shadow-lg transition-all text-left group focus:outline-none focus:ring-2 focus:ring-vault-accent focus:ring-offset-1 focus:ring-offset-vault-bg"
                >
                  {/* Cover */}
                  <div className="aspect-square bg-vault-bg relative overflow-hidden">
                    {a.cover_thumb ? (
                      <img
                        src={a.cover_thumb}
                        alt={a.artist_name}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        loading="lazy"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Users size={48} className="text-vault-text-secondary/30" />
                      </div>
                    )}
                    {/* Source badge */}
                    {(() => {
                      const s = getSourceStyle({ source: a.source, import_mode: null })
                      return (
                        <span
                          className={`absolute top-2 right-2 px-1.5 py-0.5 rounded border text-[10px] font-bold uppercase backdrop-blur-sm ${s.className}`}
                        >
                          {s.label}
                        </span>
                      )
                    })()}
                  </div>
                  {/* Info */}
                  <div className="p-3 space-y-1">
                    <p className="font-medium text-sm text-vault-text truncate">
                      {a.artist_name || a.artist_id}
                    </p>
                    <p className="text-xs text-vault-text-secondary">
                      {t('artists.galleryCount', { count: String(a.gallery_count) })}
                      {' · '}
                      {t('artists.totalPages', { count: String(a.total_pages) })}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Pagination */}
          {data?.total !== undefined && (
            <Pagination
              page={page}
              total={data.total}
              pageSize={limit}
              onChange={(p) => setPage(p)}
              isLoading={isValidating}
            />
          )}
        </>
      )}

      {viewMode === 'followed' && (
        <>
          {followedLoading ? (
            <div className="text-center py-12 text-vault-text-secondary">{t('common.loading')}</div>
          ) : !followedData?.artists?.length ? (
            <div className="flex flex-col items-center py-16 gap-3 text-vault-text-secondary">
              <Users size={48} className="opacity-30" />
              <p>{t('artists.noFollowed')}</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {followedData.artists.map((a) => (
                <button
                  key={a.id}
                  onClick={() => router.push(`/artists/${encodeURIComponent(a.artist_id)}`)}
                  className="bg-vault-card border border-vault-border rounded-xl overflow-hidden hover:border-vault-accent/50 hover:shadow-lg transition-all text-left group focus:outline-none focus:ring-2 focus:ring-vault-accent focus:ring-offset-1 focus:ring-offset-vault-bg"
                >
                  {/* Cover */}
                  <div className="aspect-square bg-vault-bg relative overflow-hidden">
                    {a.artist_avatar ? (
                      <img
                        src={a.artist_avatar}
                        alt={a.artist_name ?? a.artist_id}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        loading="lazy"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Users size={48} className="text-vault-text-secondary/30" />
                      </div>
                    )}
                    {/* Source badge */}
                    {(() => {
                      const s = getSourceStyle({ source: a.source, import_mode: null })
                      return (
                        <span
                          className={`absolute top-2 right-2 px-1.5 py-0.5 rounded border text-[10px] font-bold uppercase backdrop-blur-sm ${s.className}`}
                        >
                          {s.label}
                        </span>
                      )
                    })()}
                    {/* Auto-download badge */}
                    {a.auto_download && (
                      <span className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-500/20 text-green-400 border border-green-500/30">
                        {t('artists.autoDownload')}
                      </span>
                    )}
                  </div>
                  {/* Info */}
                  <div className="p-3 space-y-1">
                    <p className="font-medium text-sm text-vault-text truncate">
                      {a.artist_name || a.artist_id}
                    </p>
                    <p className="text-xs text-vault-text-secondary truncate">
                      {a.last_checked_at
                        ? t('artists.lastChecked', {
                            date: new Date(a.last_checked_at).toLocaleDateString(),
                          })
                        : t('artists.neverChecked')}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default function ArtistsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <ArtistsPageInner />
    </Suspense>
  )
}
