'use client'

import { useState, useCallback } from 'react'
import { Trash2, RotateCcw, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import type { Gallery } from '@/lib/types'

function daysRemaining(deletedAt: string): number {
  const deleted = new Date(deletedAt)
  const expiry = new Date(deleted.getTime() + 30 * 24 * 60 * 60 * 1000)
  const remaining = Math.ceil((expiry.getTime() - Date.now()) / (24 * 60 * 60 * 1000))
  return Math.max(0, remaining)
}

function timeAgo(iso: string | null): string {
  if (!iso) return t('settings.tasks.never')
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('history.justNow')
  if (mins < 60) return t('history.minutesAgo', { n: String(mins) })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('history.hoursAgo', { n: String(hours) })
  const days = Math.floor(hours / 24)
  return t('history.daysAgo', { n: String(days) })
}

export default function TrashPage() {
  useLocale()
  const { data, isLoading, mutate } = useSWR('trash-list', () => api.library.trashList({ limit: 200 }))
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)

  const handleRestore = useCallback(async (g: Gallery) => {
    setActionInProgress(`restore-${g.id}`)
    try {
      await api.library.restore(g.source, g.source_id)
      toast.success(t('trash.restored'))
      mutate()
    } catch {
      toast.error(t('common.failedToLoad'))
    } finally {
      setActionInProgress(null)
    }
  }, [mutate])

  const handlePermanentDelete = useCallback(async (g: Gallery) => {
    if (!confirm(t('trash.permanentDeleteConfirm'))) return
    setActionInProgress(`delete-${g.id}`)
    try {
      await api.library.permanentDelete(g.source, g.source_id)
      toast.success(t('trash.permanentlyDeleted'))
      mutate()
    } catch {
      toast.error(t('common.failedToLoad'))
    } finally {
      setActionInProgress(null)
    }
  }, [mutate])

  const handleEmptyTrash = useCallback(async () => {
    if (!confirm(t('trash.emptyTrashConfirm'))) return
    setActionInProgress('empty')
    try {
      await api.library.emptyTrash()
      toast.success(t('trash.permanentlyDeleted'))
      mutate()
    } catch {
      toast.error(t('common.failedToLoad'))
    } finally {
      setActionInProgress(null)
    }
  }, [mutate])

  const galleries = data?.galleries ?? []

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between gap-2 mb-6">
        <div className="flex items-center gap-3">
          <Trash2 size={24} className="text-vault-text-muted" />
          <h1 className="text-xl font-bold text-vault-text">{t('trash.title')}</h1>
          {data && <span className="text-sm text-vault-text-muted">({data.total})</span>}
        </div>
        {galleries.length > 0 && (
          <button
            onClick={handleEmptyTrash}
            disabled={actionInProgress === 'empty'}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-600 hover:bg-red-700 text-white transition-colors disabled:opacity-50"
          >
            <AlertTriangle size={14} />
            {t('trash.emptyTrash')}
          </button>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      )}

      {!isLoading && galleries.length === 0 && (
        <EmptyState icon={Trash2} title={t('trash.empty')} />
      )}

      {!isLoading && galleries.length > 0 && (
        <div className="space-y-2">
          {galleries.map((g) => (
            <div key={g.id} className="bg-vault-card border border-vault-border rounded-lg p-3 flex items-center gap-3">
              {g.cover_thumb && (
                <img
                  src={g.cover_thumb}
                  alt=""
                  className="w-12 h-16 object-cover rounded bg-vault-input shrink-0"
                />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-vault-text truncate">{g.title || g.title_jpn || `${g.source}/${g.source_id}`}</p>
                <div className="flex items-center gap-3 text-xs text-vault-text-muted mt-0.5">
                  <span>{t('queue.previewPages', { count: String(g.pages || 0) })}</span>
                  <span>{g.source}</span>
                  {g.deleted_at && (
                    <>
                      <span>{t('trash.deletedAt', { time: timeAgo(g.deleted_at) })}</span>
                      <span className="text-orange-400">{t('trash.daysRemaining', { days: String(daysRemaining(g.deleted_at)) })}</span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => handleRestore(g)}
                  disabled={actionInProgress === `restore-${g.id}`}
                  className="flex items-center gap-1 px-2 py-1.5 rounded text-xs font-medium bg-green-600 hover:bg-green-700 text-white transition-colors disabled:opacity-50"
                >
                  <RotateCcw size={12} />
                  {t('trash.restore')}
                </button>
                <button
                  onClick={() => handlePermanentDelete(g)}
                  disabled={actionInProgress === `delete-${g.id}`}
                  className="flex items-center gap-1 px-2 py-1.5 rounded text-xs font-medium bg-red-600 hover:bg-red-700 text-white transition-colors disabled:opacity-50"
                >
                  <Trash2 size={12} />
                  {t('trash.permanentDelete')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
