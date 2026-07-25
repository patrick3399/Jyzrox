'use client'
import { useState } from 'react'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AppImage } from '@/components/AppImage'
import type { RelationshipItem } from '@/lib/types'
import Link from 'next/link'
import { galleryHref, readerHref } from '@/lib/galleryRoutes'

interface RelationshipCardProps {
  item: RelationshipItem
  onKeep: (id: number, keepSha: string, discardRefs: number) => Promise<void>
  onWhitelist: (id: number) => Promise<void>
  onDismiss: (id: number) => Promise<void>
  onImageClick: (url: string) => void
}

export function RelationshipCard({
  item,
  onKeep,
  onWhitelist,
  onDismiss,
  onImageClick,
}: RelationshipCardProps) {
  const [loading, setLoading] = useState<string | null>(null)

  const handle = async (action: string, fn: () => Promise<void>) => {
    setLoading(action)
    try {
      await fn()
    } finally {
      setLoading(null)
    }
  }

  const isQualityConflict = item.relationship === 'quality_conflict'
  const isCandidate = item.relationship === 'needs_review'
  const aIsKeep = item.suggested_keep === item.blob_a.sha256
  const bIsKeep = item.suggested_keep === item.blob_b.sha256
  const pixelsA = (item.blob_a.width ?? 0) * (item.blob_a.height ?? 0)
  const pixelsB = (item.blob_b.width ?? 0) * (item.blob_b.height ?? 0)
  const percentDelta = (a: number, b: number) => {
    const smaller = Math.min(a, b)
    if (smaller <= 0 || a === b) return null
    return (((Math.max(a, b) - smaller) / smaller) * 100).toFixed(1)
  }
  const pixelDelta = percentDelta(pixelsA, pixelsB)
  const sizeDelta = percentDelta(item.blob_a.file_size ?? 0, item.blob_b.file_size ?? 0)

  const formatSize = (bytes: number | null) => {
    if (bytes === null || bytes === undefined) return ''
    if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
    return `${Math.round(bytes / 1024)} KB`
  }

  const diffTypeBadge = () => {
    if (!item.diff_type) return null
    if (item.diff_type === 'compression_noise') return t('dedup.diffTypeCompression')
    if (item.diff_type === 'localized_diff') return t('dedup.diffTypeLocalized')
    return item.diff_type
  }

  const reasonLabel = () => {
    if (!item.reason) return null
    if (item.reason === 'higher_resolution') return t('dedup.reasonHigherRes')
    if (item.reason === 'larger_file') return t('dedup.reasonLargerFile')
    return item.reason
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {item.hamming_dist !== null && (
            <span className="text-xs text-vault-text-muted">
              {t('dedup.pHashDist', { d: String(item.hamming_dist) })}
            </span>
          )}
          {item.diff_score !== null && (
            <span className="text-xs text-vault-text-muted">
              {t('dedup.similarity', { pct: (item.diff_score * 100).toFixed(1) })}
            </span>
          )}
          {diffTypeBadge() && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/30 text-purple-400">
              {diffTypeBadge()}
            </span>
          )}
          {reasonLabel() && <span className="text-xs text-vault-text-muted">{reasonLabel()}</span>}
          {pixelDelta && (
            <span className="text-xs text-vault-text-muted">
              {t('dedup.pixelDelta', { pct: pixelDelta })}
            </span>
          )}
          {sizeDelta && (
            <span className="text-xs text-vault-text-muted">
              {t('dedup.sizeDelta', { pct: sizeDelta })}
            </span>
          )}
        </div>
        <span
          className={`text-xs px-2 py-0.5 rounded border ${
            isCandidate
              ? 'bg-slate-500/10 border-slate-500/30 text-slate-300'
              : isQualityConflict
                ? 'bg-orange-500/10 border-orange-500/30 text-orange-400'
                : 'bg-blue-500/10 border-blue-500/30 text-blue-400'
          }`}
        >
          {isCandidate
            ? t('dedup.filterCandidate')
            : isQualityConflict
              ? t('dedup.filterQuality')
              : t('dedup.filterVariant')}
        </span>
      </div>

      {/* Image pair */}
      <div className="grid grid-cols-2 gap-2">
        {([item.blob_a, item.blob_b] as const).map((blob, idx) => {
          const isKeep = idx === 0 ? aIsKeep : bIsKeep
          const ringClass = item.suggested_keep
            ? isKeep
              ? 'ring-2 ring-green-500'
              : 'ring-2 ring-red-500'
            : ''
          const clickUrl = blob.image_url ?? blob.thumb_url ?? null
          const discardRefs = (idx === 0 ? item.blob_b : item.blob_a).occurrences.length
          return (
            <div key={blob.sha256} className="space-y-1">
              <div
                className={`aspect-square min-h-[160px] rounded-lg overflow-hidden bg-vault-input cursor-pointer ${ringClass}`}
                onClick={() => clickUrl && onImageClick(clickUrl)}
              >
                {blob.thumb_url ? (
                  <AppImage
                    src={blob.thumb_url}
                    alt=""
                    className="w-full h-full object-cover"
                    sizes="(max-width: 640px) 50vw, 320px"
                  />
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
                <p>{blob.extension.replace(/^\./, '').toUpperCase()}</p>
              </div>
              <div className="space-y-1 rounded-md border border-vault-border/70 bg-vault-input/40 p-2">
                {blob.occurrences.map((occurrence) => (
                  <div
                    key={occurrence.image_id}
                    className="min-w-0 text-[11px] text-vault-text-muted"
                  >
                    <Link
                      href={galleryHref(occurrence.source, occurrence.source_id)}
                      className="block truncate text-vault-text hover:text-vault-accent"
                      title={occurrence.gallery_title ?? occurrence.source_id}
                    >
                      {occurrence.gallery_title ?? occurrence.source_id}
                    </Link>
                    <Link
                      href={readerHref(
                        occurrence.source,
                        occurrence.source_id,
                        occurrence.page_num,
                      )}
                      className="block truncate hover:text-vault-accent"
                    >
                      #{occurrence.page_num} · {occurrence.filename ?? '—'}
                    </Link>
                  </div>
                ))}
              </div>
              <button
                onClick={() =>
                  handle(`keep-${idx}`, () => onKeep(item.id, blob.sha256, discardRefs))
                }
                disabled={!!loading}
                className="w-full px-2 py-1 rounded text-xs font-medium bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50 flex items-center justify-center gap-1"
              >
                {loading === `keep-${idx}` ? <LoadingSpinner size="sm" /> : null}
                {t('dedup.keepThis')}
              </button>
            </div>
          )
        })}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <div className="flex-1 px-3 py-1.5 rounded text-xs text-vault-text-muted text-center border border-vault-border">
          {t('dedup.selectToKeep')}
        </div>
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
