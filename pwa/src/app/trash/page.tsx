'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
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
import type {
  TrashFilters,
  TrashGallery,
  TrashReasonFilter,
  TrashSort,
  TrashSortDirection,
} from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AlertDialog } from '@/components/ui/alert-dialog'
import { useOpenedOnce } from '@/hooks/useOpenedOnce'
import { REASON_TONE, reasonLabel } from '@/components/trash/trashReason'
import {
  TrashFilterBar,
  TRASH_REASON_FILTERS,
  TRASH_SORTS,
} from '@/components/trash/TrashFilterBar'
import { TrashSummaryBar } from '@/components/trash/TrashSummaryBar'

const TrashPreviewSheet = dynamic(
  () => import('@/components/trash/TrashPreviewSheet').then((m) => m.TrashPreviewSheet),
  { ssr: false },
)

const PAGE_SIZE = 50
const DANGER_DAYS = 3
const PURGE_POLL_MS = 2000
const DEFAULT_SORT: TrashSort = 'deleted_at'
const DEFAULT_DIR: TrashSortDirection = 'desc'

function isConflict(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { status?: unknown }).status === 409
}

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
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Filters, sort and page live in the URL (`page` is 1-based, omitted for the first page).
  const q = searchParams.get('q') ?? ''
  const source = searchParams.get('source') ?? ''
  const reasonParam = searchParams.get('reason')
  const reason: TrashReasonFilter | '' = TRASH_REASON_FILTERS.includes(reasonParam as TrashReasonFilter)
    ? (reasonParam as TrashReasonFilter)
    : ''
  const sortParam = searchParams.get('sort')
  const sort: TrashSort = TRASH_SORTS.includes(sortParam as TrashSort)
    ? (sortParam as TrashSort)
    : DEFAULT_SORT
  const dir: TrashSortDirection = searchParams.get('dir') === 'asc' ? 'asc' : DEFAULT_DIR
  const pageParam = Number.parseInt(searchParams.get('page') ?? '1', 10)
  const page = Number.isFinite(pageParam) && pageParam > 1 ? pageParam - 1 : 0

  const filters: TrashFilters = {
    ...(q && { q }),
    ...(source && { source }),
    ...(reason && { reason }),
  }
  const filtersActive = q !== '' || source !== '' || reason !== ''
  const summaryKey = JSON.stringify([q, source, reason])
  const listKey = JSON.stringify([q, source, reason, sort, dir])

  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())

  const updateUrl = (patch: Record<string, string | null>, opts: { resetPage?: boolean } = {}) => {
    const params = new URLSearchParams(searchParams.toString())
    for (const [k, v] of Object.entries(patch)) {
      if (v) params.set(k, v)
      else params.delete(k)
    }
    if (opts.resetPage) {
      params.delete('page')
      setSelected(new Set())
    }
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }
  const setFilter = (patch: Record<string, string | null>) => updateUrl(patch, { resetPage: true })
  const setPage = (p: number) => updateUrl({ page: p > 0 ? String(p + 1) : null })
  const clearFilters = () => setFilter({ q: null, source: null, reason: null })

  const { data, isLoading, mutate } = useSWR(
    ['trash-list', listKey, page],
    ([, , p]: readonly [string, string, number]) =>
      api.library.trashList({
        limit: PAGE_SIZE,
        offset: p * PAGE_SIZE,
        ...filters,
        ...(sort !== DEFAULT_SORT && { sort }),
        ...(dir !== DEFAULT_DIR && { direction: dir }),
      }),
    { keepPreviousData: true },
  )
  const { data: summary, mutate: mutateSummary } = useSWR(
    ['trash-summary', summaryKey],
    () => api.library.trashSummary(filters),
    {
      keepPreviousData: true,
      // Poll only while a background purge is running; WS events cover the rest.
      refreshInterval: (latest) => (latest?.purge ? PURGE_POLL_MS : 0),
    },
  )
  const purging = summary?.purge != null
  const { data: featuresData } = useSWR('settings/features', () => api.settings.getFeatures())
  const trashEnabled = featuresData?.trash_enabled ?? true
  const retentionDays = featuresData?.trash_retention_days ?? 30

  const [busy, setBusy] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
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
      void mutateSummary()
      if (fresh && fresh.galleries.length === 0 && page > 0) {
        setPage(Math.max(0, Math.min(page - 1, Math.ceil(fresh.total / PAGE_SIZE) - 1)))
      }
      return true
    } catch (err) {
      if (isConflict(err)) {
        toast.error(t('trash.purgeAlreadyRunning'))
        void mutateSummary()
      } else {
        toast.error(t('trash.actionFailed'))
      }
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
        const res = await api.library.trashRestore({ all: true, ...filters })
        return t('trash.restoredCount', { count: String(res.affected) })
      })
    } else if (c.kind === 'empty') {
      ok = await run(async () => {
        const res = await api.library.emptyTrash(filters)
        return res?.status === 'queued' ? t('trash.purgeQueued') : t('trash.permanentlyDeleted')
      })
    } else if (c.kind === 'deleteSelected') {
      const ids = Array.from(selected)
      ok = await run(async () => {
        const res = await api.library.trashPurge(ids)
        return res.status === 'queued'
          ? t('trash.purgeQueued')
          : t('trash.deletedCount', { count: String(res.total ?? 0) })
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
      ? { title: t('trash.restoreAll'), body: t(filtersActive ? 'trash.restoreFilteredConfirm' : 'trash.restoreAllConfirm', { count: String(confirmCount) }), label: t('trash.restoreAll'), destructive: false }
      : confirm?.kind === 'empty'
        ? { title: t('trash.emptyTrash'), body: t(filtersActive ? 'trash.emptyFilteredConfirm' : 'trash.emptyTrashConfirmCount', { count: String(confirmCount) }), label: t('trash.emptyTrash'), destructive: true }
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
                disabled={busy || purging}
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
                disabled={busy || purging}
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

      {trashEnabled && (
        <div className="space-y-2">
          <TrashFilterBar
            q={q}
            source={source}
            reason={reason}
            sort={sort}
            dir={dir}
            sources={summary?.sources ?? []}
            onSearchChange={(v) => setFilter({ q: v || null })}
            onSourceChange={(v) => setFilter({ source: v || null })}
            onReasonChange={(v) => setFilter({ reason: v || null })}
            onSortChange={(v) => setFilter({ sort: v === DEFAULT_SORT ? null : v })}
            onDirChange={(v) => setFilter({ dir: v === DEFAULT_DIR ? null : v })}
          />
          {summary && <TrashSummaryBar summary={summary} />}
        </div>
      )}

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

      {!isLoading && trashEnabled && galleries.length === 0 && filtersActive && (
        <div className="flex flex-col items-center">
          <EmptyState icon={Trash2} title={t('trash.noMatches')} />
          <Button
            variant="secondary"
            size="sm"
            onClick={clearFilters}
            data-testid="trash-clear-filters"
          >
            {t('trash.clearFilters')}
          </Button>
        </div>
      )}

      {!isLoading && trashEnabled && galleries.length === 0 && !filtersActive && (
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
                  disabled={busy || purging || selected.size === 0}
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
                    disabled={busy || purging}
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
          deleteDisabled={purging}
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
