'use client'

import { Button } from '@/components/ui/button'
import { useEffect, useMemo, useRef, useState } from 'react'
import useSWR from 'swr'
import { ArrowDownAZ, ArrowUpAZ, Eye, EyeOff, FileImage, RotateCcw, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'

import { SkeletonGrid } from '@/components/Skeleton'
import { useExplorerSelection } from '@/hooks/useExplorerSelection'
import { markSelectionEntry } from '@/hooks/explorerHistory'
import { useExplorerScrollRestore } from '@/hooks/useExplorerScrollRestore'
import { useExplorerUrlState } from '@/hooks/useExplorerUrlState'
import { useWorkbenchKeyboard, type WorkbenchGlobalShortcuts } from '@/hooks/useWorkbenchKeyboard'
import { api } from '@/lib/api'
import type {
  ExplorerGalleryImages,
  ExplorerImageItem,
  ExplorerImageMedia,
  ExplorerImageSort,
  ExplorerImageSummary,
  ExplorerImageVisibility,
} from '@/lib/api/explorer'
import { formatBytes, t } from '@/lib/i18n'

import { ContextMenu, type ContextMenuEntry } from './ContextMenu'
import { ImageTile, imageKey, isImageHidden } from './ImageTile'
import { PurgeDialog } from './PurgeDialog'
import { SelectionMarquee } from './SelectionMarquee'
import type { ContentView } from './shared'

export const IMAGE_PAGE_SIZE = 200

export interface ImageInspectData {
  summary: ExplorerImageSummary
  canEdit: boolean
  /** The single selected image, otherwise the focused one. */
  image: ExplorerImageItem | null
  selectedCount: number
}

interface GalleryImagePaneProps {
  galleryId: number
  source: string
  sourceId: string
  view: ContentView
  coarse: boolean
  /** False while a dialog or the shortcut reference owns the keyboard. */
  keyboardEnabled: boolean
  shortcuts: WorkbenchGlobalShortcuts
  onOpenImage: (image: ExplorerImageItem) => void
  /** Called after hide / restore / purge so roots (smart-view counts) can refresh. */
  onChanged: () => void
  onInspect: (data: ImageInspectData | null) => void
}

const selectClass = 'rounded-md border border-vault-border bg-vault-bg px-2 py-1.5 text-sm text-vault-text'

/** The Gallery node of the Workbench: filterable, paginated image grid with selection, context menu, and hide / purge actions. */
export function GalleryImagePane({
  galleryId,
  source,
  sourceId,
  view,
  coarse,
  keyboardEnabled,
  shortcuts,
  onOpenImage,
  onChanged,
  onInspect,
}: GalleryImagePaneProps) {
  // Filters and page live in the URL so a Reader round trip (or reload) restores them.
  const { ivis: visibility, imedia: media, isort: sort, idir: direction, ioffset: offset, urlKey, refine } = useExplorerUrlState()
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [purge, setPurge] = useState<{ imageIds?: number[]; allHidden?: boolean } | null>(null)
  const [columns, setColumns] = useState(1)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const gridRef = useRef<HTMLDivElement | null>(null)

  const swrKey = galleryId > 0 ? (['explorer-gallery-images', galleryId, visibility, media, sort, direction, offset] as const) : null
  const { data, error, isLoading, mutate } = useSWR<ExplorerGalleryImages, Error>(
    swrKey,
    ([, id, v, m, s, d, o]: NonNullable<typeof swrKey>) =>
      api.explorer.galleryImages(id, { visibility: v, media: m, sort: s, direction: d, offset: o, limit: IMAGE_PAGE_SIZE }),
  )
  const items = useMemo(() => data?.items ?? [], [data])
  const keys = useMemo(() => items.map(imageKey), [items])
  const canEdit = data?.can_edit ?? false
  const summary = data?.summary

  const selection = useExplorerSelection({ keys, scrollRef, marqueeEnabled: !coarse, toggleOnClick: coarse })
  const selectedImages = useMemo(
    () => items.filter((image) => selection.selectedKeys.has(imageKey(image))),
    [items, selection.selectedKeys],
  )
  const hiddenSelected = selectedImages.filter(isImageHidden)
  const activeSelected = selectedImages.filter((image) => !isImageHidden(image))
  const allSelectedHidden = selectedImages.length > 0 && activeSelected.length === 0

  const refreshAll = async () => {
    await mutate()
    onChanged()
  }

  const hideImages = async (images: ExplorerImageItem[]) => {
    const ids = images.filter((image) => !isImageHidden(image)).map((image) => image.image_id)
    if (!canEdit || ids.length === 0) return
    try {
      const result = await api.library.hideImagesBatch(source, sourceId, ids)
      selection.clear()
      toast.success(t('library.imagesHidden', { count: result.hidden }), {
        action: {
          label: t('common.undo'),
          onClick: async () => {
            try {
              await api.library.restoreImagesBatch(source, sourceId, ids)
              toast.success(t('library.hiddenRestored'))
              await refreshAll()
            } catch {
              toast.error(t('library.restoreFailed'))
            }
          },
        },
      })
      await refreshAll()
    } catch {
      toast.error(t('library.hideImageFailed'))
    }
  }

  const restoreImages = async (images: ExplorerImageItem[]) => {
    const ids = images.filter(isImageHidden).map((image) => image.image_id)
    if (!canEdit || ids.length === 0) return
    try {
      const result = await api.library.restoreImagesBatch(source, sourceId, ids)
      selection.clear()
      toast.success(t('explorer.imagesRestored', { count: result.restored }))
      await refreshAll()
    } catch {
      toast.error(t('library.restoreFailed'))
    }
  }

  const requestPurge = (images: ExplorerImageItem[]) => {
    if (!canEdit || images.length === 0 || !images.every(isImageHidden)) return
    setPurge({ imageIds: images.map((image) => image.image_id) })
  }

  const openImage = (index: number) => {
    const image = items[index]
    if (image && !isImageHidden(image)) onOpenImage(image)
  }

  const { focusedIndex, focusIndex, registerElement } = useWorkbenchKeyboard({
    ...shortcuts,
    itemCount: items.length,
    columnCount: columns,
    listMode: view === 'list',
    enabled: keyboardEnabled && menu === null && purge === null,
    onOpen: openImage,
    onToggleSelection: selection.toggle,
    onExtendSelection: selection.extendTo,
    onSelectAll: selection.selectAll,
    onClearSelection: () => {
      if (selection.selectedKeys.size === 0) return false
      selection.clear()
      return true
    },
    onDelete: () => { void hideImages(selectedImages) },
    onPurge: () => requestPurge(selectedImages),
  })
  const resetView = () => {
    selection.clear()
    focusIndex(null)
  }
  const changeVisibility = (next: ExplorerImageVisibility) => { refine({ ivis: next, ioffset: 0 }); resetView() }
  const changeMedia = (next: ExplorerImageMedia) => { refine({ imedia: next, ioffset: 0 }); resetView() }
  const changeSort = (next: ExplorerImageSort) => {
    refine({ isort: next, idir: next === 'size' ? 'desc' : 'asc', ioffset: 0 })
    resetView()
  }
  const toggleDirection = () => { refine({ idir: direction === 'asc' ? 'desc' : 'asc', ioffset: 0 }); resetView() }
  const goToOffset = (next: number) => { refine({ ioffset: next }); resetView() }

  useEffect(() => {
    const element = gridRef.current
    if (!element) return
    if (view === 'list') {
      setColumns(1)
      return
    }
    const update = () => setColumns(Math.max(1, window.getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length))
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [items.length, view])

  useExplorerScrollRestore(scrollRef, urlKey, Boolean(data) && items.length > 0)

  const selectionActive = selection.selectedKeys.size > 0
  const clearSelection = selection.clear
  useEffect(() => {
    if (!coarse || !selectionActive) return
    window.history.pushState({ explorerSelection: true }, '')
    markSelectionEntry()
    window.addEventListener('popstate', clearSelection, { once: true })
    return () => window.removeEventListener('popstate', clearSelection)
  }, [coarse, selectionActive, clearSelection])

  const inspected = selectedImages.length === 1 ? selectedImages[0] : (focusedIndex !== null ? items[focusedIndex] ?? null : null)
  useEffect(() => {
    onInspect(summary ? { summary, canEdit, image: inspected ?? null, selectedCount: selectedImages.length } : null)
  }, [summary, canEdit, inspected, selectedImages.length, onInspect])
  useEffect(() => () => onInspect(null), [onInspect])

  const openContextMenu = (index: number, x: number, y: number) => {
    const key = keys[index]
    if (key !== undefined && !selection.selectedKeys.has(key)) selection.selectOnly(index)
    focusIndex(index)
    setMenu({ x, y })
  }

  const menuItems: ContextMenuEntry[] = [
    {
      id: 'open',
      label: t('explorer.open'),
      icon: Eye,
      disabled: selectedImages.length !== 1 || isImageHidden(selectedImages[0]),
      onSelect: () => { if (selectedImages[0]) onOpenImage(selectedImages[0]) },
    },
  ]
  if (canEdit) {
    menuItems.push(
      { id: 'hide', label: t('explorer.hideImages'), icon: EyeOff, disabled: activeSelected.length === 0, separator: true, onSelect: () => void hideImages(selectedImages) },
      { id: 'restore', label: t('explorer.restoreImages'), icon: RotateCcw, disabled: hiddenSelected.length === 0, onSelect: () => void restoreImages(selectedImages) },
      { id: 'purge', label: t('explorer.purgeImages'), icon: Trash2, danger: true, separator: true, disabled: !allSelectedHidden, onSelect: () => requestPurge(selectedImages) },
    )
  }

  const total = data?.total ?? 0
  const limit = data?.limit ?? IMAGE_PAGE_SIZE

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-vault-border px-4 py-2 text-sm" data-testid="image-filter-bar">
        <select aria-label={t('explorer.filterVisibility')} value={visibility} onChange={(event) => changeVisibility(event.target.value as ExplorerImageVisibility)} className={selectClass}>
          <option value="active">{t('explorer.visibilityActive')}</option>
          <option value="hidden">{t('explorer.visibilityHidden')}</option>
          <option value="all">{t('explorer.visibilityAll')}</option>
        </select>
        <select aria-label={t('explorer.filterMedia')} value={media} onChange={(event) => changeMedia(event.target.value as ExplorerImageMedia)} className={selectClass}>
          <option value="all">{t('explorer.mediaAll')}</option>
          <option value="image">{t('explorer.mediaImage')}</option>
          <option value="video">{t('explorer.mediaVideo')}</option>
          <option value="gif">{t('explorer.mediaGif')}</option>
        </select>
        <select aria-label={t('explorer.sortBy')} value={sort} onChange={(event) => changeSort(event.target.value as ExplorerImageSort)} className={selectClass}>
          <option value="page">{t('explorer.sortPage')}</option>
          <option value="size">{t('explorer.sortSize')}</option>
        </select>
        <Button variant="secondary" size="icon" className="size-8" type="button" aria-label={t('explorer.sortDirection')} title={direction === 'asc' ? t('explorer.sortAscending') : t('explorer.sortDescending')} onClick={toggleDirection}>
          {direction === 'asc' ? <ArrowUpAZ size={16} /> : <ArrowDownAZ size={16} />}
        </Button>
        {summary && (
          <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-vault-text-muted" data-testid="image-summary">
            <span>{t('explorer.activeSummary', { count: summary.active_count, bytes: formatBytes(summary.active_bytes) })}</span>
            {summary.hidden_count > 0 && <span>{t('explorer.hiddenSummary', { count: summary.hidden_count, bytes: formatBytes(summary.hidden_bytes) })}</span>}
            {canEdit && summary.hidden_count > 0 && (
              <Button variant="ghost" size="sm" className="border border-red-500/40 text-red-400 hover:bg-red-500/10" type="button" data-testid="empty-hidden" onClick={() => setPurge({ allHidden: true })}>
                <Trash2 size={13} />{t('explorer.emptyHidden', { count: summary.hidden_count, bytes: formatBytes(summary.hidden_reclaimable_bytes) })}
              </Button>
            )}
          </div>
        )}
      </div>

      <div
        ref={scrollRef}
        data-testid="image-scroll-area"
        onPointerDown={selection.onContainerPointerDown}
        className="relative min-h-0 flex-1 select-none overflow-y-auto pb-24 lg:pb-4"
      >
        {error ? (
          <div className="m-4 rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
            <p>{error.message || t('common.errorOccurred')}</p>
            <Button variant="secondary" size="sm" className="mt-3" type="button" onClick={() => void mutate()}>{t('common.retry')}</Button>
          </div>
        ) : isLoading && !data ? (
          <div className="p-4"><SkeletonGrid /></div>
        ) : items.length === 0 ? (
          <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 p-8 text-vault-text-muted"><FileImage size={42} strokeWidth={1.2} /><p>{t('explorer.noImages')}</p></div>
        ) : (
          <div ref={gridRef} className={view === 'grid' ? 'grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 xl:grid-cols-5' : 'p-2'}>
            {items.map((image, index) => (
              <ImageTile
                key={image.image_id}
                image={image}
                view={view}
                selected={selection.selectedKeys.has(imageKey(image))}
                selectionMode={selection.selectedKeys.size > 0}
                coarse={coarse}
                focused={focusedIndex === index}
                tabIndex={focusedIndex === null ? (index === 0 ? 0 : -1) : (focusedIndex === index ? 0 : -1)}
                elementRef={(element) => { registerElement(index, element); selection.registerItem(imageKey(image), element) }}
                onFocus={() => focusIndex(index)}
                onClick={(event) => { focusIndex(index); selection.onItemClick(index, event) }}
                onToggle={() => { focusIndex(index); selection.toggle(index) }}
                onOpen={() => openImage(index)}
                onContextMenuAt={(x, y) => openContextMenu(index, x, y)}
              />
            ))}
          </div>
        )}
        <SelectionMarquee rect={selection.marquee} />
        {total > limit && (
          <div className="flex items-center justify-center gap-3 p-4">
            <Button variant="secondary" size="sm" type="button" disabled={offset === 0} onClick={() => goToOffset(Math.max(0, offset - limit))}>{t('common.prev')}</Button>
            <span className="text-sm text-vault-text-muted">{offset + 1}–{Math.min(offset + limit, total)} / {total}</span>
            <Button variant="secondary" size="sm" type="button" disabled={offset + limit >= total} onClick={() => goToOffset(offset + limit)}>{t('common.next')}</Button>
          </div>
        )}
      </div>

      {selectedImages.length > 0 && (
        <div data-testid="image-action-bar" className="fixed inset-x-2 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-50 flex max-w-[calc(100vw-1rem)] items-center gap-1 overflow-x-auto rounded-xl border border-vault-border bg-vault-card p-2 shadow-2xl lg:inset-x-auto lg:bottom-5 lg:left-1/2 lg:-translate-x-1/2">
          <Button variant="ghost" size="icon" className="size-8" type="button" aria-label={t('explorer.clearSelection')} onClick={() => selection.clear()}><X size={18} /></Button>
          <span className="mr-2 whitespace-nowrap text-sm font-medium text-vault-text">{t('explorer.selectedCount', { count: selectedImages.length })}</span>
          {canEdit && (
            <>
              <Button variant="ghost" size="sm" type="button" data-testid="action-hide" disabled={activeSelected.length === 0} onClick={() => void hideImages(selectedImages)}><EyeOff size={16} /><span className="hidden sm:inline">{t('explorer.hideImages')}</span></Button>
              <Button variant="ghost" size="sm" type="button" data-testid="action-restore" disabled={hiddenSelected.length === 0} onClick={() => void restoreImages(selectedImages)}><RotateCcw size={16} /><span className="hidden sm:inline">{t('explorer.restoreImages')}</span></Button>
              <Button variant="ghost" size="sm" className="text-red-400 hover:bg-red-500/10" type="button" data-testid="action-purge" disabled={!allSelectedHidden} onClick={() => requestPurge(selectedImages)}><Trash2 size={16} /><span className="hidden sm:inline">{t('explorer.purgeImages')}</span></Button>
            </>
          )}
        </div>
      )}

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems} ariaLabel={t('explorer.contextMenu')} onClose={() => setMenu(null)} />}
      {purge && (
        <PurgeDialog
          galleryId={galleryId}
          imageIds={purge.imageIds}
          allHidden={purge.allHidden}
          onClose={() => setPurge(null)}
          onDone={() => { selection.clear(); void refreshAll() }}
        />
      )}
    </>
  )
}
