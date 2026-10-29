'use client'

import { formatBytes, t } from '@/lib/i18n'

import type { ImageInspectData } from './ImageGrid'
import { formatDuration } from './shared'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase text-vault-text-muted">{label}</dt>
      <dd className="mt-1 break-words text-vault-text">{value}</dd>
    </div>
  )
}

/** Inspector for a Gallery node: storage summary plus the focused or single selected image. */
export function ImageInspector({ data }: { data: ImageInspectData | null }) {
  const asideClass = 'h-full overflow-y-auto border-l border-vault-border p-5 outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent'
  if (!data) {
    return <aside data-explorer-inspector tabIndex={-1} className={`${asideClass} text-sm text-vault-text-muted`}>{t('explorer.inspectorEmpty')}</aside>
  }
  const { summary, image } = data
  return (
    <aside data-explorer-inspector data-testid="image-inspector" tabIndex={-1} className={asideClass}>
      <h2 className="font-semibold text-vault-text">{t('explorer.imageStorage')}</h2>
      <dl className="mt-4 space-y-4 text-sm">
        <Row label={t('explorer.visibilityActive')} value={t('explorer.activeSummary', { count: summary.active_count, bytes: formatBytes(summary.active_bytes) })} />
        <Row label={t('explorer.visibilityHidden')} value={t('explorer.hiddenSummary', { count: summary.hidden_count, bytes: formatBytes(summary.hidden_bytes) })} />
        {summary.hidden_count > 0 && <Row label={t('explorer.reclaimable')} value={formatBytes(summary.hidden_reclaimable_bytes)} />}
      </dl>
      {image && (
        <>
          <h2 className="mt-6 break-words font-semibold text-vault-text">{image.filename}</h2>
          <dl className="mt-4 space-y-4 text-sm">
            <Row label={t('explorer.fileSize')} value={image.file_size != null ? formatBytes(image.file_size) : '—'} />
            <Row label={t('explorer.dimensions')} value={image.width && image.height ? `${image.width} × ${image.height}` : '—'} />
            {image.duration != null && <Row label={t('explorer.duration')} value={formatDuration(image.duration)} />}
            <Row label={t('explorer.fileType')} value={image.media_type} />
            <Row label={t('explorer.storage')} value={(image.storage === 'cas' ? t('explorer.storageCas') : image.storage === 'external' ? t('explorer.storageExternal') : t('explorer.storagePending'))} />
            {image.shared && <Row label={t('explorer.sharedBadge')} value={t('explorer.sharedHint')} />}
            {image.visibility === 'hidden' && <Row label={t('explorer.hiddenBadge')} value={image.hidden_at ?? '—'} />}
          </dl>
        </>
      )}
    </aside>
  )
}
