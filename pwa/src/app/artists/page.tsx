'use client'

import { useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Users } from 'lucide-react'
import { useArtists } from '@/hooks/useArtists'
import { Pagination } from '@/components/Pagination'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  ehentai: 'bg-orange-500/20 text-orange-400',
  twitter: 'bg-sky-500/20 text-sky-400',
}

export default function ArtistsPage() {
  useLocale()
  const router = useRouter()
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [source, setSource] = useState('')
  const [sort, setSort] = useState<'latest' | 'gallery_count' | 'total_pages'>('latest')
  const [page, setPage] = useState(0)
  const limit = 30

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

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-vault-text">{t('artists.title')}</h1>

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
          onChange={(e) => { setSource(e.target.value); setPage(0) }}
          className="px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text focus:outline-none focus:ring-1 focus:ring-vault-accent"
        >
          <option value="">{t('common.all')}</option>
          <option value="pixiv">Pixiv</option>
          <option value="ehentai">E-Hentai</option>
          <option value="twitter">Twitter</option>
        </select>
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value as typeof sort); setPage(0) }}
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
      ) : !data?.artists?.length ? (
        <div className="text-center py-12 text-vault-text-secondary">{t('artists.noArtists')}</div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7 gap-4">
          {data.artists.map((a) => (
            <button
              key={a.artist_id}
              onClick={() => router.push(`/artists/${encodeURIComponent(a.artist_id)}`)}
              className="bg-vault-card border border-vault-border rounded-xl overflow-hidden hover:border-vault-accent/50 hover:shadow-lg transition-all text-left group"
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
                <span
                  className={`absolute top-2 right-2 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${SOURCE_COLORS[a.source] ?? 'bg-vault-text-secondary/20 text-vault-text-secondary'}`}
                >
                  {a.source}
                </span>
              </div>
              {/* Info */}
              <div className="p-3 space-y-1">
                <p className="font-medium text-sm text-vault-text truncate">{a.artist_name || a.artist_id}</p>
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
    </div>
  )
}
