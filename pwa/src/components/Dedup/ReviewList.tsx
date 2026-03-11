'use client'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { RelationshipCard } from './RelationshipCard'
import { ImageModal } from './ImageModal'
import { useDedupReview, useDedupSettings } from '@/hooks/useDedup'
import { api } from '@/lib/api'

const FILTERS = [
  { key: '', label: () => t('dedup.filterAll') },
  { key: 'quality_conflict', label: () => t('dedup.filterQuality') },
  { key: 'variant', label: () => t('dedup.filterVariant') },
]

export function ReviewList() {
  const [filter, setFilter] = useState('')
  const [modalUrl, setModalUrl] = useState<string | null>(null)
  const { data: features } = useDedupSettings()
  const phashEnabled = features?.dedup_phash_enabled ?? false
  const { items, hasMore, loadMore, isLoading, mutate } = useDedupReview(filter || undefined)

  useEffect(() => {
    void mutate()
  }, [filter, mutate])

  const handleKeep = async (id: number, keepSha: string) => {
    try {
      await api.dedup.keep(id, keepSha)
      toast.success(t('dedup.keptSuccess'))
      mutate()
    } catch {
      toast.error(t('dedup.keepFailed'))
    }
  }

  const handleWhitelist = async (id: number) => {
    try {
      await api.dedup.whitelist(id)
      toast.success(t('dedup.whitelistSuccess'))
      mutate()
    } catch {
      toast.error(t('dedup.whitelistFailed'))
    }
  }

  const handleDismiss = async (id: number) => {
    try {
      await api.dedup.dismiss(id)
      toast.success(t('dedup.dismissSuccess'))
      mutate()
    } catch {
      toast.error(t('dedup.dismissFailed'))
    }
  }

  if (!phashEnabled) {
    return (
      <EmptyState
        title={t('dedup.emptyNotEnabled')}
        description={t('dedup.emptyNotEnabledDesc')}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium text-vault-text text-sm">{t('dedup.reviewTitle')}</h2>
        {/* Filter tabs */}
        <div className="flex gap-1">
          {FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1.5 rounded text-xs transition-colors ${
                filter === f.key
                  ? 'bg-vault-accent/20 text-vault-accent'
                  : 'text-vault-text-muted hover:text-vault-text hover:bg-vault-card-hover'
              }`}
            >
              {f.label()}
            </button>
          ))}
        </div>
      </div>

      {isLoading && items.length === 0 ? (
        <div className="flex justify-center py-8"><LoadingSpinner /></div>
      ) : items.length === 0 ? (
        <EmptyState
          title={t('dedup.emptyDone')}
          description={t('dedup.emptyDoneDesc')}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {items.map(item => (
              <RelationshipCard
                key={item.id}
                item={item}
                onKeep={handleKeep}
                onWhitelist={handleWhitelist}
                onDismiss={handleDismiss}
                onImageClick={setModalUrl}
              />
            ))}
          </div>
          {hasMore && (
            <div className="flex justify-center pt-2">
              <button
                onClick={loadMore}
                disabled={isLoading}
                className="px-4 py-2 rounded text-sm font-medium bg-vault-card border border-vault-border text-vault-text-muted hover:text-vault-text transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {isLoading && <LoadingSpinner size="sm" />}
                {t('dedup.loadMore')}
              </button>
            </div>
          )}
        </>
      )}

      {modalUrl && <ImageModal url={modalUrl} onClose={() => setModalUrl(null)} />}
    </div>
  )
}
