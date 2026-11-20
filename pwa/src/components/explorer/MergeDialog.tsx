'use client'

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import type { ExplorerGalleryItem } from '@/lib/api'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { galleryName } from './shared'
import { Modal } from './Modal'

export function MergeDialog({
  selection,
  onClose,
  onDone,
}: {
  selection: ExplorerGalleryItem[]
  onClose: () => void
  onDone: () => void
}) {
  const [targetId, setTargetId] = useState(selection[0]?.id ?? 0)
  const [preview, setPreview] = useState<Awaited<
    ReturnType<typeof api.explorer.mergePreview>
  > | null>(null)
  const [scalarSources, setScalarSources] = useState<Record<string, number>>({})
  const [working, setWorking] = useState(false)

  useEffect(() => {
    let active = true
    setPreview(null)
    api.explorer
      .mergePreview({ gallery_ids: selection.map((item) => item.id), target_id: targetId })
      .then((value) => {
        if (!active) return
        setPreview(value)
        setScalarSources(
          Object.fromEntries(Object.keys(value.scalar_conflicts).map((field) => [field, targetId])),
        )
      })
      .catch((error) =>
        toast.error(error instanceof Error ? error.message : t('common.errorOccurred')),
      )
    return () => {
      active = false
    }
  }, [selection, targetId])

  const merge = async () => {
    setWorking(true)
    try {
      await api.explorer.merge({
        gallery_ids: selection.map((item) => item.id),
        target_id: targetId,
        scalar_sources: scalarSources,
      })
      toast.success(t('explorer.mergeComplete'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setWorking(false)
    }
  }

  return (
    <Modal
      title={t('explorer.mergeGalleries')}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="danger" disabled={!preview || working} onClick={merge}>
            {working ? t('common.loading') : t('explorer.mergeGalleries')}
          </Button>
        </>
      }
    >
      <div className="space-y-5 p-5">
        <label className="block text-sm text-vault-text">
          {t('explorer.mergeTarget')}
          <select
            value={targetId}
            onChange={(event) => setTargetId(Number(event.target.value))}
            className="mt-2 w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2"
          >
            {selection.map((item) => (
              <option key={item.id} value={item.id}>
                {galleryName(item)}
              </option>
            ))}
          </select>
        </label>
        {preview ? (
          <>
            <div className="grid grid-cols-3 gap-3 rounded-lg border border-vault-border p-4 text-center">
              <div>
                <p className="text-xl font-semibold text-vault-text">{preview.images.add}</p>
                <p className="text-xs text-vault-text-muted">{t('explorer.imagesAdded')}</p>
              </div>
              <div>
                <p className="text-xl font-semibold text-vault-text">
                  {preview.images.exact_sha_skipped}
                </p>
                <p className="text-xs text-vault-text-muted">{t('explorer.exactSkipped')}</p>
              </div>
              <div>
                <p className="text-xl font-semibold text-vault-text">
                  {preview.images.similar_kept_for_review}
                </p>
                <p className="text-xs text-vault-text-muted">{t('explorer.similarReview')}</p>
              </div>
            </div>
            {Object.entries(preview.scalar_conflicts).length > 0 && (
              <div className="space-y-3">
                <p className="text-sm font-medium text-vault-text">
                  {t('explorer.resolveConflicts')}
                </p>
                {Object.entries(preview.scalar_conflicts).map(([field, choices]) => (
                  <label
                    key={field}
                    className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3 text-sm text-vault-text-muted"
                  >
                    <span>{field}</span>
                    <select
                      value={scalarSources[field] || targetId}
                      onChange={(event) =>
                        setScalarSources((current) => ({
                          ...current,
                          [field]: Number(event.target.value),
                        }))
                      }
                      className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-vault-text"
                    >
                      {choices.map((choice) => (
                        <option key={choice.gallery_id} value={choice.gallery_id}>
                          {String(choice.value ?? '—')}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            )}
          </>
        ) : (
          <div className="flex justify-center p-6">
            <Loader2 className="animate-spin" />
          </div>
        )}
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          {t('explorer.merge404Warning')}
        </div>
      </div>
    </Modal>
  )
}
