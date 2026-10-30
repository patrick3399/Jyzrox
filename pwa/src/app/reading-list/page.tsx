'use client'

import { useState, useCallback } from 'react'
import { BookMarked, X } from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { galleryHref } from '@/lib/galleryRoutes'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { AppImage } from '@/components/AppImage'
import type { Gallery } from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'

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
    <PageContainer variant="secondary">
      <PageHeader
        title={t('readingList.title')}
        icon={<BookMarked size={24} className="text-vault-text-muted" />}
        meta={data?.total !== undefined ? `(${data.total})` : undefined}
      />

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
              onClick={() => router.push(galleryHref(g.source, g.source_id))}
            >
              {g.cover_thumb && (
                <AppImage
                  src={g.cover_thumb}
                  sizes="48px"
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
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleRemove(g)
                  }}
                  disabled={removingId === g.id}
                  className="gap-1 text-xs hover:border-red-500/50 hover:text-red-400"
                  aria-label={t('readingList.remove')}
                >
                  <X size={12} />
                  {t('readingList.remove')}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageContainer>
  )
}
