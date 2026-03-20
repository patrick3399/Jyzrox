'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { VirtualGrid } from '@/components/VirtualGrid'
import { toast } from 'sonner'
import { X, Trash2, Clock } from 'lucide-react'
import type { BrowseHistoryItem } from '@/lib/types'

const PAGE_SIZE = 24

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return t('history.justNow')
  if (mins < 60) return t('history.minutesAgo', { n: String(mins) })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('history.hoursAgo', { n: String(hours) })
  const days = Math.floor(hours / 24)
  if (days < 30) return t('history.daysAgo', { n: String(days) })
  return new Date(iso).toLocaleDateString()
}

function sourceLabel(source: string): string {
  if (source === 'ehentai' || source === 'exhentai') return t('history.source.ehentai')
  if (source === 'local') return t('history.source.local')
  if (source === 'twitter') return t('history.source.twitter')
  return source
}

function HistoryCard({
  item,
  onDelete,
  onClick,
}: {
  item: BrowseHistoryItem
  onDelete: (id: number) => void
  onClick: () => void
}) {
  const thumbSrc = item.thumb
    ? (item.source === 'ehentai' || item.source === 'exhentai') && item.thumb.startsWith('http')
      ? `/api/eh/thumb-proxy?url=${encodeURIComponent(item.thumb)}`
      : item.thumb
    : null

  return (
    <div className="relative group">
      <button
        onClick={onClick}
        className="w-full text-left bg-vault-card border border-vault-border rounded-lg overflow-hidden
                   hover:border-vault-border-hover hover:bg-vault-card-hover transition-colors"
      >
        {/* Thumbnail */}
        <div className="aspect-[3/4] bg-vault-input overflow-hidden">
          {thumbSrc ? (
            <img
              src={thumbSrc}
              alt={item.title}
              className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
              loading="lazy"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <Clock size={32} className="text-vault-text-muted" />
            </div>
          )}
        </div>

        {/* Info */}
        <div className="p-2">
          <p className="text-xs text-vault-text line-clamp-2 leading-snug font-medium">
            {item.title}
          </p>
          <div className="flex items-center justify-between mt-1.5">
            <span className="text-[10px] text-vault-text-muted">{sourceLabel(item.source)}</span>
            <span className="text-[10px] text-vault-text-muted">
              {formatRelativeTime(item.viewed_at)}
            </span>
          </div>
        </div>
      </button>

      {/* Delete button */}
      <button
        onClick={(e) => {
          e.stopPropagation()
          onDelete(item.id)
        }}
        className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/60 text-white/70
                   hover:text-white hover:bg-black/80 opacity-0 group-hover:opacity-100
                   transition-opacity"
        title={t('history.remove')}
      >
        <X size={12} />
      </button>
    </div>
  )
}

export default function HistoryPage() {
  const router = useRouter()
  const [items, setItems] = useState<BrowseHistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [clearing, setClearing] = useState(false)

  const loadPage = useCallback(async (offset: number, replace: boolean) => {
    if (offset === 0) setLoading(true)
    else setLoadingMore(true)
    try {
      const data = await api.history.list({ limit: PAGE_SIZE, offset })
      setTotal(data.total)
      if (replace) {
        setItems(data.items)
      } else {
        setItems((prev) => [...prev, ...data.items])
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [])

  useEffect(() => {
    loadPage(0, true)
  }, [loadPage])

  const handleDelete = useCallback(async (id: number) => {
    try {
      await api.history.delete(id)
      toast.success(t('history.deleted'))
      setItems((prev) => prev.filter((i) => i.id !== id))
      setTotal((prev) => prev - 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('history.deleteFailed'))
    }
  }, [])

  const handleClearAll = useCallback(async () => {
    if (!window.confirm(t('history.clearConfirm'))) return
    setClearing(true)
    try {
      await api.history.clear()
      toast.success(t('history.cleared'))
      setItems([])
      setTotal(0)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('history.clearFailed'))
    } finally {
      setClearing(false)
    }
  }, [])

  const handleClick = useCallback(
    (item: BrowseHistoryItem) => {
      if (item.gid != null && item.token) {
        router.push(`/e-hentai/${item.gid}/${item.token}`)
      } else {
        router.push(`/library/${item.source}/${item.source_id}`)
      }
    },
    [router],
  )

  const hasMore = items.length < total

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-vault-text">{t('history.title')}</h1>
          <p className="text-sm text-vault-text-muted mt-0.5">{t('history.subtitle')}</p>
        </div>
        {items.length > 0 && (
          <button
            onClick={handleClearAll}
            disabled={clearing}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-red-700/50
                         bg-red-900/20 text-red-400 hover:bg-red-900/40 transition-colors text-sm"
          >
            <Trash2 size={14} />
            {clearing ? '...' : t('history.clearAll')}
          </button>
        )}
      </div>

      {/* Count */}
      {!loading && total > 0 && (
        <p className="text-xs text-vault-text-muted mb-4">
          {items.length} / {total}
        </p>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <Clock size={48} className="text-vault-text-muted mb-4" />
          <p className="text-vault-text-secondary font-medium">{t('history.noHistory')}</p>
          <p className="text-vault-text-muted text-sm mt-1">{t('history.noHistoryHint')}</p>
        </div>
      ) : (
        <VirtualGrid
          items={items}
          columns={{ base: 4, sm: 5, md: 6, lg: 8, xl: 12, xxl: 15 }}
          gap={12}
          estimateHeight={250}
          renderItem={(item) => (
            <HistoryCard
              key={item.id}
              item={item}
              onDelete={handleDelete}
              onClick={() => handleClick(item)}
            />
          )}
          onLoadMore={() => loadPage(items.length, false)}
          hasMore={hasMore}
          isLoading={loadingMore}
        />
      )}
    </>
  )
}
