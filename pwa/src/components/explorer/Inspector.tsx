'use client'

import useSWR from 'swr'
import { HardDrive } from 'lucide-react'
import { api } from '@/lib/api'
import type { ExplorerGalleryItem, ExplorerPhysicalEntry, ExplorerRoots } from '@/lib/api'
import { formatBytes, t } from '@/lib/i18n'
import { galleryName } from './shared'

export function Inspector({
  item,
  physicalRoot,
}: {
  item?: ExplorerGalleryItem | ExplorerPhysicalEntry
  physicalRoot?: ExplorerRoots['physical'][number]
}) {
  const gallery = item && 'id' in item ? item : null
  const galleryId = gallery?.id ?? 0
  const { data: metadataHistory } = useSWR(
    galleryId > 0 ? ['explorer-metadata-history', galleryId] : null,
    () => api.explorer.metadataHistory(galleryId),
  )
  if (!item && !physicalRoot) {
    return (
      <aside
        data-explorer-inspector
        tabIndex={-1}
        className="h-full border-l border-vault-border p-5 text-sm text-vault-text-muted outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent"
      >
        {t('explorer.inspectorEmpty')}
      </aside>
    )
  }
  if (physicalRoot && !item) {
    return (
      <aside
        data-explorer-inspector
        tabIndex={-1}
        className="h-full overflow-y-auto border-l border-vault-border p-5 outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent"
      >
        <HardDrive size={28} className="mb-3 text-vault-accent" />
        <h2 className="font-semibold text-vault-text">{physicalRoot.label}</h2>
        <p className="mt-4 text-xs uppercase text-vault-text-muted">{t('explorer.physicalSize')}</p>
        <p className="mt-1 text-lg text-vault-text">
          {physicalRoot.physical_bytes == null
            ? t('explorer.calculating')
            : formatBytes(physicalRoot.physical_bytes)}
        </p>
        <p className="mt-2 text-xs text-vault-text-muted">{t('explorer.readOnlyPhysical')}</p>
      </aside>
    )
  }
  if (!item) return null
  const physical = 'id' in item ? null : item
  const name = gallery ? galleryName(gallery) : (physical?.name ?? '')
  return (
    <aside
      data-explorer-inspector
      tabIndex={-1}
      className="h-full overflow-y-auto border-l border-vault-border p-5 outline-none focus:ring-2 focus:ring-inset focus:ring-vault-accent"
    >
      <h2 className="break-words font-semibold text-vault-text">{name}</h2>
      {gallery ? (
        <dl className="mt-5 space-y-4 text-sm">
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">{t('explorer.source')}</dt>
            <dd className="mt-1 text-vault-text">{gallery.source}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">{t('explorer.logicalSize')}</dt>
            <dd className="mt-1 text-vault-text">{formatBytes(gallery.logical_bytes)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">
              {t('explorer.uniqueCasSize')}
            </dt>
            <dd className="mt-1 text-vault-text">{formatBytes(gallery.unique_cas_bytes)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">{t('explorer.metadata')}</dt>
            <dd className="mt-1 text-vault-text">
              {[gallery.artist_id, gallery.category, gallery.language]
                .filter(Boolean)
                .join(' · ') || '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">{t('explorer.visibility')}</dt>
            <dd className="mt-1 text-vault-text">{gallery.visibility}</dd>
          </div>
          {metadataHistory && Object.entries(metadataHistory.fields).length > 0 && (
            <div>
              <dt className="text-xs uppercase text-vault-text-muted">
                {t('explorer.provenance')}
              </dt>
              <dd className="mt-2 space-y-2">
                {Object.entries(metadataHistory.fields).map(([field, state]) => {
                  const current = gallery[field as keyof ExplorerGalleryItem]
                  const pending =
                    state.locked &&
                    state.source_value !== null &&
                    String(state.source_value) !== String(current ?? '')
                  return (
                    <div key={field} className="rounded border border-vault-border p-2">
                      <div className="flex items-center justify-between">
                        <span className="text-vault-text">{field}</span>
                        <span className="text-[10px] uppercase text-vault-text-muted">
                          {state.origin}
                          {state.locked ? ' · locked' : ''}
                        </span>
                      </div>
                      {pending && (
                        <p className="mt-1 text-xs text-amber-400">
                          {t('explorer.sourceProposal')}: {String(state.source_value)}
                        </p>
                      )}
                    </div>
                  )
                })}
              </dd>
            </div>
          )}
          {metadataHistory && metadataHistory.changes.length > 0 && (
            <div>
              <dt className="text-xs uppercase text-vault-text-muted">{t('explorer.history')}</dt>
              <dd className="mt-2 space-y-2">
                {metadataHistory.changes.slice(0, 5).map((change) => (
                  <div key={change.id} className="text-xs text-vault-text-muted">
                    <span className="text-vault-text">{change.field}</span> · {change.origin}
                  </div>
                ))}
              </dd>
            </div>
          )}
        </dl>
      ) : physical ? (
        <dl className="mt-5 space-y-4 text-sm">
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">{t('explorer.type')}</dt>
            <dd className="mt-1 text-vault-text">{physical.kind}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-vault-text-muted">
              {t('explorer.physicalSize')}
            </dt>
            <dd className="mt-1 text-vault-text">
              {physical.kind === 'folder'
                ? physical.physical_bytes == null
                  ? t('explorer.calculating')
                  : formatBytes(physical.physical_bytes)
                : formatBytes(physical.size || 0)}
            </dd>
          </div>
          {physical.kind === 'folder' && (
            <div>
              <dt className="text-xs uppercase text-vault-text-muted">
                {t('explorer.importStatus')}
              </dt>
              <dd className="mt-1 text-vault-text">
                {physical.gallery_id ? t('explorer.imported') : t('explorer.notImported')}
              </dd>
            </div>
          )}
        </dl>
      ) : null}
    </aside>
  )
}
