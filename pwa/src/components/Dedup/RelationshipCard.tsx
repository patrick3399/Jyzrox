'use client'
import { useState } from 'react'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import type { RelationshipItem } from '@/lib/types'

interface RelationshipCardProps {
  item: RelationshipItem
  onKeep: (id: number, keepSha: string) => Promise<void>
  onWhitelist: (id: number) => Promise<void>
  onDismiss: (id: number) => Promise<void>
  onImageClick: (url: string) => void
}

export function RelationshipCard({ item, onKeep, onWhitelist, onDismiss, onImageClick }: RelationshipCardProps) {
  const [loading, setLoading] = useState<string | null>(null)

  const handle = async (action: string, fn: () => Promise<void>) => {
    setLoading(action)
    try { await fn() } finally { setLoading(null) }
  }

  const aIsKeep = item.suggested_keep === item.blob_a.sha256
  const bIsKeep = item.suggested_keep === item.blob_b.sha256

  const formatSize = (bytes: number | null) => {
    if (bytes === null || bytes === undefined) return ''
    if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
    return `${Math.round(bytes / 1024)} KB`
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {item.hamming_dist !== null && (
            <span className="text-xs text-vault-text-muted">
              {t('dedup.pHashDist', { d: String(item.hamming_dist) })}
            </span>
          )}
        </div>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          item.relationship === 'quality_conflict'
            ? 'bg-orange-500/10 border-orange-500/30 text-orange-400'
            : 'bg-blue-500/10 border-blue-500/30 text-blue-400'
        }`}>
          {item.relationship === 'quality_conflict' ? t('dedup.filterQuality') : t('dedup.filterVariant')}
        </span>
      </div>

      {/* Image pair */}
      <div className="grid grid-cols-2 gap-2">
        {([item.blob_a, item.blob_b] as const).map((blob, idx) => {
          const isKeep = idx === 0 ? aIsKeep : bIsKeep
          const ringClass = item.relationship === 'quality_conflict'
            ? (isKeep ? 'ring-2 ring-green-500' : 'ring-2 ring-red-500')
            : ''
          return (
            <div key={blob.sha256} className="space-y-1">
              <div
                className={`aspect-square min-h-[160px] rounded-lg overflow-hidden bg-vault-input cursor-pointer ${ringClass}`}
                onClick={() => blob.thumb_url && onImageClick(blob.thumb_url)}
              >
                {blob.thumb_url ? (
                  <img src={blob.thumb_url} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-vault-text-muted text-xs">
                    {t('dedup.noPreview')}
                  </div>
                )}
              </div>
              <div className="text-xs text-vault-text-muted space-y-0.5">
                {blob.width && blob.height && (
                  <p>{t('dedup.resolution', { w: String(blob.width), h: String(blob.height) })}</p>
                )}
                {blob.file_size !== null && <p>{formatSize(blob.file_size)}</p>}
              </div>
            </div>
          )
        })}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={() => handle('keep', () => onKeep(item.id, item.suggested_keep ?? item.blob_a.sha256))}
          disabled={!!loading}
          className="flex-1 px-3 py-1.5 rounded text-xs font-medium bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
        >
          {loading === 'keep' ? <LoadingSpinner size="sm" /> : null}
          {t('dedup.actionKeep')}
        </button>
        <button
          onClick={() => handle('whitelist', () => onWhitelist(item.id))}
          disabled={!!loading}
          className="flex-1 px-3 py-1.5 rounded text-xs font-medium bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5"
        >
          {loading === 'whitelist' ? <LoadingSpinner size="sm" /> : null}
          {t('dedup.actionWhitelist')}
        </button>
        <button
          onClick={() => handle('dismiss', () => onDismiss(item.id))}
          disabled={!!loading}
          className="px-3 py-1.5 rounded text-xs font-medium bg-vault-input border border-vault-border text-vault-text-muted hover:text-vault-text transition-colors disabled:opacity-50"
        >
          {t('dedup.actionDismiss')}
        </button>
      </div>
    </div>
  )
}
