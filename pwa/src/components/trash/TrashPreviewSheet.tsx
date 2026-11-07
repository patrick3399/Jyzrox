'use client'

import Link from 'next/link'
import useSWRInfinite from 'swr/infinite'
import { ImageOff, RotateCcw, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { t, formatBytes } from '@/lib/i18n'
import { galleryHref } from '@/lib/galleryRoutes'
import type { TrashGallery, TrashPreview } from '@/lib/types'
import { AppImage } from '@/components/AppImage'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { REASON_TONE, reasonLabel } from './trashReason'

export const PREVIEW_LIMIT = 60

interface TrashPreviewSheetProps {
  gallery: TrashGallery | null
  open: boolean
  onOpenChange: (open: boolean) => void
  busy?: boolean
  /** Disables permanent delete only (e.g. while a background purge runs). */
  deleteDisabled?: boolean
  onRestore: (gallery: TrashGallery) => void
  onDelete: (gallery: TrashGallery) => void
}

function PreviewBody({ gallery }: { gallery: TrashGallery }) {
  const galleryId = gallery.id
  const { data, size, setSize, isLoading, isValidating, error } = useSWRInfinite<TrashPreview>(
    (index) => ['trash-preview', galleryId, index + 1],
    ([, id, page]: readonly [string, number, number]) =>
      api.library.trashPreview(id, { page, limit: PREVIEW_LIMIT }),
    { revalidateFirstPage: false },
  )

  const first = data?.[0]
  const images = (data ?? []).flatMap((p) => p.images)
  const total = first?.images_total ?? 0
  const hasMore = images.length < total
  const counts = first?.media.counts
  const g = first?.gallery ?? gallery

  return (
    <div className="space-y-4">
      <div className="space-y-1.5 text-sm">
        <p className="font-medium text-vault-text break-words">
          {g.title || g.title_jpn || `${g.source}/${g.source_id}`}
        </p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-vault-text-muted">
          <span>{g.source}</span>
          <span>{t('queue.previewPages', { count: String(g.pages || 0) })}</span>
          {first && (
            <span>
              {t('trash.previewSize')}: {formatBytes(first.media.total_size)}
              {counts && counts.video + counts.gif > 0
                ? ` (${counts.image} / ${counts.gif} GIF / ${counts.video} video)`
                : ''}
            </span>
          )}
          {g.deleted_reason && (
            <Badge tone={REASON_TONE[g.deleted_reason]}>{reasonLabel(g.deleted_reason)}</Badge>
          )}
          {g.deleted_by && <span>{t('trash.deletedBy', { name: g.deleted_by.username })}</span>}
        </div>
        {g.merged_into && (
          <p className="text-xs text-vault-text-muted">
            {t('trash.mergedInto')}:{' '}
            <Link
              href={galleryHref(g.merged_into.source, g.merged_into.source_id)}
              className="text-vault-accent hover:underline"
            >
              {g.merged_into.title || `${g.merged_into.source}/${g.merged_into.source_id}`}
            </Link>
          </p>
        )}
      </div>

      {g.tags_array && g.tags_array.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {g.tags_array.map((tag) => (
            <span
              key={tag}
              className="rounded bg-vault-input px-1.5 py-0.5 text-xs text-vault-text-secondary"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {isLoading && (
        <div className="flex justify-center py-6">
          <LoadingSpinner />
        </div>
      )}
      {error && !data && (
        <p className="text-sm text-vault-danger">{t('trash.actionFailed')}</p>
      )}

      {images.length > 0 && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4" data-testid="trash-preview-grid">
          {images.map((img) => (
            <div
              key={img.id}
              className="flex aspect-[3/4] items-center justify-center overflow-hidden rounded bg-vault-input"
            >
              {img.thumb_path ? (
                <AppImage
                  src={img.thumb_path}
                  srcSet={img.thumb_srcset ?? undefined}
                  sizes="160px"
                  alt=""
                  className="h-full w-full object-cover"
                />
              ) : (
                <span
                  className="flex flex-col items-center gap-1 text-vault-text-muted"
                  title={t('trash.previewNoThumb')}
                >
                  <ImageOff size={18} />
                  <span className="text-[10px]">{img.page_num}</span>
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {hasMore && (
        <div className="flex justify-center">
          <Button
            variant="secondary"
            size="sm"
            data-testid="trash-preview-load-more"
            disabled={isValidating}
            onClick={() => setSize(size + 1)}
          >
            {t('trash.previewLoadMore')}
          </Button>
        </div>
      )}
    </div>
  )
}

export function TrashPreviewSheet({
  gallery,
  open,
  onOpenChange,
  busy = false,
  deleteDisabled = false,
  onRestore,
  onDelete,
}: TrashPreviewSheetProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={gallery?.title || gallery?.title_jpn || t('trash.preview')}
      size="xl"
      dismissible={!busy}
      className="min-h-[50dvh]"
      footer={
        gallery && (
          <>
            <Button
              variant="primary"
              size="sm"
              data-testid="trash-preview-restore"
              disabled={busy}
              onClick={() => onRestore(gallery)}
            >
              <RotateCcw size={14} />
              {t('trash.restore')}
            </Button>
            <Button
              variant="danger"
              size="sm"
              data-testid="trash-preview-delete"
              disabled={busy || deleteDisabled}
              onClick={() => onDelete(gallery)}
            >
              <Trash2 size={14} />
              {t('trash.permanentDelete')}
            </Button>
          </>
        )
      }
    >
      <div data-testid="trash-preview-sheet">
        {gallery && <PreviewBody key={gallery.id} gallery={gallery} />}
      </div>
    </Dialog>
  )
}
