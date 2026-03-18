'use client'

import { useState, useCallback } from 'react'
import { BookMarked, X } from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import type { Gallery } from '@/lib/types'

export default function ReadingListPage() {
  useLocale()
  const router = useRouter()
  const { data, isLoading, mutate } = useSWR('reading-list', () =>
    api.library.getGalleries({ in_reading_list: true, limit: 100 }),
  )
  const [removingId, setRemovingId] = useState<number | null>(null)

  const handleRemove = useCallback(
    async (g: Gallery) => {
      setRemovingId(g.id)
      try {
        await api.library.updateGallery(g.source, g.source_id, { in_reading_list: false })
        toast.success(t('contextMenu.removeFromReadingList'))
        mutate()
      } catch {
        toast.error(t('common.failedToLoad'))
      } finally {
        setRemovingId(null)
      }
    },
    [mutate],
  )

  const galleries = data?.galleries ?? []

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <div className="flex items-center gap-3 mb-6">
        <BookMarked size={24} className="text-vault-text-muted" />
        <h1 className="text-xl font-bold text-vault-text">{t('readingList.title')}</h1>
        {data?.total !== undefined && (
          <span className="text-sm text-vault-text-muted">({data.total})</span>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}

      {!isLoading && galleries.length === 0 && (
        <EmptyState
          icon={BookMarked}
          title={t('readingList.empty')}
          description={t('readingList.emptyDescription')}
        />
      )}

      {!isLoading && galleries.length > 0 && (
        <div className="space-y-2">
          {galleries.map((g) => (
            <div
              key={g.id}
              className="bg-vault-card border border-vault-border rounded-lg p-3 flex items-center gap-3 cursor-pointer hover:border-vault-accent transition-colors"
              onClick={() => router.push(`/library/${g.source}/${g.source_id}`)}
            >
              {g.cover_thumb && (
                <img
                  src={g.cover_thumb}
                  alt=""
                  className="w-12 h-16 object-cover rounded bg-vault-input shrink-0"
                />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-vault-text truncate">
                  {g.title || g.title_jpn || `${g.source}/${g.source_id}`}
                </p>
                <div className="flex items-center gap-3 text-xs text-vault-text-muted mt-0.5">
                  <span>{g.pages}p</span>
                  <span>{g.source}</span>
                </div>
              </div>
              <div className="shrink-0">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleRemove(g)
                  }}
                  disabled={removingId === g.id}
                  className="flex items-center gap-1 px-2 py-1.5 rounded text-xs font-medium bg-vault-input border border-vault-border text-vault-text-secondary hover:border-red-500/50 hover:text-red-400 transition-colors disabled:opacity-50"
                  aria-label={t('readingList.remove')}
                >
                  <X size={12} />
                  {t('readingList.remove')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
