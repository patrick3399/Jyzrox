'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { Trash2, RotateCcw, AlertTriangle, CheckSquare } from 'lucide-react'
import { toast } from 'sonner'
import useSWR, { useSWRConfig } from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { AppImage } from '@/components/AppImage'
import { Pagination } from '@/components/Pagination'
import type { TrashGallery } from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AlertDialog } from '@/components/ui/alert-dialog'
import { useOpenedOnce } from '@/hooks/useOpenedOnce'
import { REASON_TONE, reasonLabel } from '@/components/trash/trashReason'

const TrashPreviewSheet = dynamic(
  () => import('@/components/trash/TrashPreviewSheet').then((m) => m.TrashPreviewSheet),
  { ssr: false },
)

const PAGE_SIZE = 50
const DANGER_DAYS = 3

function daysRemaining(deletedAt: string, retentionDays: number = 30): number {
  const deleted = new Date(deletedAt)
  const expiry = new Date(deleted.getTime() + retentionDays * 24 * 60 * 60 * 1000)
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

type Confirm =
  | { kind: 'restoreAll' }
  | { kind: 'empty' }
  | { kind: 'deleteSelected' }
  | { kind: 'deleteOne'; gallery: TrashGallery }

export default function TrashPage() {
  useLocale()
  const { mutate: mutateGlobal } = useSWRConfig()
  const [page, setPage] = useState(0)
  const { data, isLoading, mutate } = useSWR(
    ['trash-list', page],
    ([, p]: readonly [string, number]) =>
      api.library.trashList({ limit: PAGE_SIZE, offset: p * PAGE_SIZE }),
    { keepPreviousData: true },
  )
  const { data: featuresData } = useSWR('settings/features', () => api.settings.getFeatures())
  const trashEnabled = featuresData?.trash_enabled ?? true
  const retentionDays = featuresData?.trash_retention_days ?? 30

  const [busy, setBusy] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [previewGallery, setPreviewGallery] = useState<TrashGallery | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const previewLoaded = useOpenedOnce(previewOpen)

  const galleries = data?.galleries ?? []
  const total = data?.total ?? 0

  const exitSelectMode = () => {
    setSelectMode(false)
    setSelected(new Set())
  }

  const changePage = (p: number) => {
    setPage(p)
    setSelected(new Set())
  }

  // Runs a mutation, then refreshes the list and nav badge. Steps back one
  // page when the current page became empty.
  const run = async (action: () => Promise<string>) => {
    setBusy(true)
    try {
      const message = await action()
      toast.success(message)
      setSelected(new Set())
      const fresh = await mutate()
      void mutateGlobal('nav-counts/trash')
      if (fresh && fresh.galleries.length === 0 && page > 0) {
        setPage(Math.max(0, Math.min(page - 1, Math.ceil(fresh.total / PAGE_SIZE) - 1)))
      }
      return true
    } catch {
      toast.error(t('trash.actionFailed'))
      return false
    } finally {
      setBusy(false)
    }
  }

  const restoreIds = async (ids: number[]) => {
    await run(async () => {
      const res = await api.library.trashRestore({ gallery_ids: ids })
      return t('trash.restoredCount', { count: String(res.affected) })
    })
  }

  const restoreOne = async (g: TrashGallery) => {
    const ok = await run(async () => {
      await api.library.restore(g.source, g.source_id)
      return t('trash.restored')
    })
    if (ok) setPreviewOpen(false)
  }

  const handleConfirm = async () => {
    const c = confirm
    if (!c) return
    let ok = false
    if (c.kind === 'restoreAll') {
      ok = await run(async () => {
        const res = await api.library.trashRestore({ all: true })
        return t('trash.restoredCount', { count: String(res.affected) })
      })
    } else if (c.kind === 'empty') {
      ok = await run(async () => {
        await api.library.emptyTrash()
        return t('trash.permanentlyDeleted')
      })
    } else if (c.kind === 'deleteSelected') {
      const ids = Array.from(selected)
      ok = await run(async () => {
        const res = await api.library.trashPurge(ids)
        return t('trash.deletedCount', { count: String(res.affected) })
      })
    } else {
      const g = c.gallery
      ok = await run(async () => {
        await api.library.permanentDelete(g.source, g.source_id)
        return t('trash.permanentlyDeleted')
      })
      if (ok) setPreviewOpen(false)
    }
    if (ok) setConfirm(null)
  }

  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const pageIds = galleries.map((g) => g.id)
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id))
  const toggleSelectPage = () => {
    setSelected(allPageSelected ? new Set() : new Set(pageIds))
  }

  const openPreview = (g: TrashGallery) => {
    setPreviewGallery(g)
    setPreviewOpen(true)
  }

  const confirmCount =
    confirm?.kind === 'deleteSelected' ? selected.size : confirm?.kind === 'deleteOne' ? 1 : total
  const confirmText =
    confirm?.kind === 'restoreAll'
      ? { title: t('trash.restoreAll'), body: t('trash.restoreAllConfirm', { count: String(confirmCount) }), label: t('trash.restoreAll'), destructive: false }
      : confirm?.kind === 'empty'
        ? { title: t('trash.emptyTrash'), body: t('trash.emptyTrashConfirmCount', { count: String(confirmCount) }), label: t('trash.emptyTrash'), destructive: true }
        : confirm?.kind === 'deleteSelected'
          ? { title: t('trash.deleteSelected'), body: t('trash.deleteSelectedConfirm', { count: String(confirmCount) }), label: t('trash.permanentDelete'), destructive: true }
          : { title: t('trash.permanentDelete'), body: t('trash.permanentDeleteConfirm'), label: t('trash.permanentDelete'), destructive: true }

  return (
    <PageContainer variant="secondary">
      <PageHeader
        title={t('trash.title')}
        icon={<Trash2 size={24} className="text-vault-text-muted" />}
        meta={data ? `(${data.total})` : undefined}
        actions={
          trashEnabled &&
          total > 0 && (
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
                className="text-xs"
                data-testid="trash-select-mode"
              >
                <CheckSquare size={14} />
                {selectMode ? t('trash.cancelSelect') : t('trash.select')}
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setConfirm({ kind: 'restoreAll' })}
                disabled={busy}
                className="text-xs"
                data-testid="trash-restore-all"
              >
                <RotateCcw size={14} />
                {t('trash.restoreAll')}
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => setConfirm({ kind: 'empty' })}
                disabled={busy}
                className="text-xs"
                data-testid="trash-empty"
              >
                <AlertTriangle size={14} />
                {t('trash.emptyTrash')}
              </Button>
            </div>
          )
        }
      />

      {isLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}

      {!isLoading && !trashEnabled && (
        <EmptyState
          icon={Trash2}
          title={t('trash.disabled')}
          description={t('trash.disabledDesc')}
        />
      )}

      {!isLoading && trashEnabled && galleries.length === 0 && (
        <EmptyState icon={Trash2} title={t('trash.empty')} />
      )}

      {!isLoading && trashEnabled && galleries.length > 0 && (
        <div className="space-y-2">
          {selectMode && (
            <div className="bg-vault-card border border-vault-border rounded-lg p-2 flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-vault-text-secondary px-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={toggleSelectPage}
                  data-testid="trash-select-page"
                />
                {t('trash.selectPage')}
              </label>
              <span className="text-xs text-vault-text-muted">
                {t('trash.selectedCount', { count: String(selected.size) })}
              </span>
              <div className="ml-auto flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  disabled={busy || selected.size === 0}
                  onClick={() => restoreIds(Array.from(selected))}
                  className="text-xs"
                  data-testid="trash-restore-selected"
                >
                  <RotateCcw size={12} />
                  {t('trash.restoreSelected')}
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={busy || selected.size === 0}
                  onClick={() => setConfirm({ kind: 'deleteSelected' })}
                  className="text-xs"
                  data-testid="trash-delete-selected"
                >
                  <Trash2 size={12} />
                  {t('trash.deleteSelected')}
                </Button>
              </div>
            </div>
          )}

          {galleries.map((g) => {
            const days = daysRemaining(g.deleted_at, retentionDays)
            const title = g.title || g.title_jpn || `${g.source}/${g.source_id}`
            return (
              <div
                key={g.id}
                className="bg-vault-card border border-vault-border rounded-lg p-3 flex items-center gap-3"
              >
                {selectMode && (
                  <input
                    type="checkbox"
                    checked={selected.has(g.id)}
                    onChange={() => toggleSelected(g.id)}
                    aria-label={title}
                    data-testid={`trash-select-${g.id}`}
                    className="shrink-0"
                  />
                )}
                <button
                  type="button"
                  onClick={() => openPreview(g)}
                  data-testid={`trash-row-${g.id}`}
                  aria-label={`${t('trash.preview')}: ${title}`}
                  className="flex flex-1 min-w-0 items-center gap-3 text-left rounded focus-visible:outline-2 focus-visible:outline-vault-accent"
                >
                  {g.cover_thumb && (
                    <AppImage
                      src={g.cover_thumb}
                      sizes="48px"
                      alt=""
                      className="w-12 h-16 object-cover rounded bg-vault-input shrink-0"
                    />
                  )}
                  <span className="block flex-1 min-w-0">
                    <span className="block text-sm font-medium text-vault-text truncate">
                      {title}
                    </span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-vault-text-muted">
                      {g.deleted_reason && (
                        <Badge tone={REASON_TONE[g.deleted_reason]}>
                          {reasonLabel(g.deleted_reason)}
                        </Badge>
                      )}
                      <span>{t('queue.previewPages', { count: String(g.pages || 0) })}</span>
                      <span>{g.source}</span>
                      {g.deleted_by && (
                        <span>{t('trash.deletedBy', { name: g.deleted_by.username })}</span>
                      )}
                      <span>{t('trash.deletedAt', { time: timeAgo(g.deleted_at) })}</span>
                      <span className={days <= DANGER_DAYS ? 'text-vault-danger' : 'text-orange-400'}>
                        {t('trash.daysRemaining', { days: String(days) })}
                      </span>
                    </span>
                  </span>
                </button>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => restoreOne(g)}
                    disabled={busy}
                    className="gap-1 text-xs"
                  >
                    <RotateCcw size={12} />
                    {t('trash.restore')}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => setConfirm({ kind: 'deleteOne', gallery: g })}
                    disabled={busy}
                    className="gap-1 text-xs"
                  >
                    <Trash2 size={12} />
                    {t('trash.permanentDelete')}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {trashEnabled && total > PAGE_SIZE && (
        <Pagination page={page} total={total} pageSize={PAGE_SIZE} onChange={changePage} />
      )}

      {previewLoaded && (
        <TrashPreviewSheet
          gallery={previewGallery}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          busy={busy}
          onRestore={restoreOne}
          onDelete={(g) => setConfirm({ kind: 'deleteOne', gallery: g })}
        />
      )}

      <AlertDialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null)
        }}
        title={confirmText.title}
        description={confirmText.body}
        confirmLabel={confirmText.label}
        destructive={confirmText.destructive}
        busy={busy}
        onConfirm={handleConfirm}
      />
    </PageContainer>
  )
}
