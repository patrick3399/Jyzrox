'use client'

import { Button } from '@/components/ui/button'
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { api } from '@/lib/api'
import type { ExplorerPurgeResult } from '@/lib/api/explorer'
import { formatBytes, t } from '@/lib/i18n'

import { Modal } from './ExplorerDialogs'

interface PurgeDialogProps {
  galleryId: number
  /** Selected hidden images; omit together with `allHidden` to purge every hidden image. */
  imageIds?: number[]
  allHidden?: boolean
  onClose: () => void
  onDone: (result: ExplorerPurgeResult) => void
}

function Stat({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="rounded-lg border border-vault-border p-3 text-center">
      <p data-testid={testId} className="text-lg font-semibold text-vault-text">{value}</p>
      <p className="text-xs text-vault-text-muted">{label}</p>
    </div>
  )
}

/** Permanent deletion of hidden images: dry-run preview first, then a confirmed real call. */
export function PurgeDialog({ galleryId, imageIds, allHidden = false, onClose, onDone }: PurgeDialogProps) {
  const [preview, setPreview] = useState<ExplorerPurgeResult | null>(null)
  const [failed, setFailed] = useState(false)
  const [working, setWorking] = useState(false)
  const idsKey = (imageIds ?? []).join(',')

  useEffect(() => {
    let active = true
    setPreview(null)
    setFailed(false)
    const body = allHidden ? { all_hidden: true } : { image_ids: idsKey ? idsKey.split(',').map(Number) : [] }
    api.explorer.purgeImages(galleryId, { ...body, dry_run: true })
      .then((value) => { if (active) setPreview(value) })
      .catch((error) => {
        if (!active) return
        setFailed(true)
        toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
      })
    return () => { active = false }
  }, [galleryId, allHidden, idsKey])

  const confirm = async () => {
    setWorking(true)
    try {
      const body = allHidden ? { all_hidden: true } : { image_ids: idsKey ? idsKey.split(',').map(Number) : [] }
      const result = await api.explorer.purgeImages(galleryId, { ...body, dry_run: false })
      toast.success(t('explorer.purgeDone', { count: result.purged, bytes: formatBytes(result.reclaim_bytes) }))
      onDone(result)
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setWorking(false)
    }
  }

  const otherSkipped = preview ? preview.skipped_not_hidden + preview.skipped_pending + preview.skipped_missing : 0

  return (
    <Modal title={t('explorer.purgeTitle')} onClose={onClose}>
      <div className="space-y-4 p-5" data-testid="purge-dialog">
        {preview ? (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Stat testId="purge-purgeable" label={t('explorer.purgeable')} value={String(preview.purgeable)} />
              <Stat testId="purge-reclaim" label={t('explorer.purgeReclaim')} value={formatBytes(preview.reclaim_bytes)} />
              <Stat testId="purge-shared" label={t('explorer.purgeSharedKept')} value={String(preview.shared_kept)} />
              <Stat testId="purge-external" label={t('explorer.purgeExternalSkipped')} value={String(preview.skipped_external)} />
            </div>
            {otherSkipped > 0 && (
              <p className="text-xs text-vault-text-muted">{t('explorer.purgeOtherSkipped', { count: otherSkipped })}</p>
            )}
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">{t('explorer.purgeWarning')}</div>
          </>
        ) : failed ? (
          <p className="text-sm text-red-300">{t('common.errorOccurred')}</p>
        ) : (
          <div className="flex justify-center p-6"><Loader2 className="animate-spin" /></div>
        )}
      </div>
      <footer className="flex justify-end gap-2 border-t border-vault-border px-5 py-4">
        <Button variant="ghost" size="md" type="button" onClick={onClose}>{t('common.cancel')}</Button>
        <Button variant="danger" size="md"
          type="button"
          data-testid="purge-confirm"
          disabled={!preview || preview.purgeable === 0 || working}
          onClick={() => void confirm()}
        >
          {working ? t('common.loading') : t('explorer.purgeConfirm')}
        </Button>
      </footer>
    </Modal>
  )
}
