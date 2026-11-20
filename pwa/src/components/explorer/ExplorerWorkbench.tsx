'use client'

import { Button } from '@/components/ui/button'
import { CategoryFilter } from './CategoryFilter'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import {
  Archive,
  ChevronRight,
  Columns3,
  Database,
  Edit3,
  ExternalLink,
  Folder,
  FolderOpen,
  FolderTree,
  Grid2X2,
  Keyboard,
  Layers3,
  List,
  Merge,
  RefreshCw,
  Search,
  Heart,
  Tags,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { SkeletonGrid } from '@/components/Skeleton'
import { AppImage } from '@/components/AppImage'
import { useExplorerSelection } from '@/hooks/useExplorerSelection'
import { markSelectionEntry, saveExplorerScroll } from '@/hooks/explorerHistory'
import { useExplorerScrollRestore } from '@/hooks/useExplorerScrollRestore'
import { useExplorerUrlState, type ExplorerNode } from '@/hooks/useExplorerUrlState'
import { useWorkbenchKeyboard, type WorkbenchGlobalShortcuts } from '@/hooks/useWorkbenchKeyboard'
import { api } from '@/lib/api'
import type { ExplorerGalleryItem, ExplorerPhysicalEntry, ExplorerQuery } from '@/lib/api'
import { readerHref } from '@/lib/galleryRoutes'
import { t } from '@/lib/i18n'
import { ContextMenu, type ContextMenuEntry } from './ContextMenu'
import { MergeDialog, MetadataDialog, Modal, OrganizeDialog } from './ExplorerDialogs'
import { GalleryImagePane, type ImageInspectData } from './ImageGrid'
import { ImageInspector } from './ImageInspector'
import { SelectionMarquee } from './SelectionMarquee'
import { FinderColumns } from './FinderColumns'
import { Inspector } from './Inspector'
import { NavigationTree, UNCATEGORIZED_ID, categoryNodeLabel } from './ExplorerNavigation'
import { SelectableCard } from './SelectableCard'
import { galleryName, type ContentView, type QuerySelection } from './shared'

type LayoutMode = 'xnview' | 'finder'
type WorkbenchNode = ExplorerNode

function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(false)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(pointer: coarse)')
    const update = () => setCoarse(media.matches)
    update()
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [])
  return coarse
}

function cycleExplorerPane() {
  const navigation = document.querySelector<HTMLElement>('[data-explorer-navigation]')
  const content = document.querySelector<HTMLElement>('[data-explorer-item][tabindex="0"]')
  const inspector = document.querySelector<HTMLElement>('[data-explorer-inspector]')
  const active = document.activeElement
  if (active instanceof HTMLElement && active.closest('[data-explorer-navigation]'))
    content?.focus()
  else if (active instanceof HTMLElement && active.closest('[data-explorer-item]'))
    inspector?.focus()
  else
    (
      navigation?.querySelector<HTMLButtonElement>('button[aria-current="page"]') ??
      navigation?.querySelector<HTMLButtonElement>('button')
    )?.focus()
}

function galleryQuery(
  node: WorkbenchNode,
  query: string,
  offset: number,
  sort: NonNullable<ExplorerQuery['sort']>,
  direction: NonNullable<ExplorerQuery['direction']>,
  category: string | null,
): ExplorerQuery | null {
  const kind = node.kind
  if (
    kind !== 'source' &&
    kind !== 'category' &&
    kind !== 'collection' &&
    kind !== 'artist' &&
    kind !== 'saved_search' &&
    kind !== 'smart' &&
    kind !== 'trash'
  )
    return null
  return {
    node_kind: kind,
    node_id: node.id,
    query,
    sort,
    direction,
    offset,
    limit: 60,
    category,
    facets: true,
  }
}

function itemKey(item: ExplorerGalleryItem | ExplorerPhysicalEntry): string {
  return 'id' in item ? `gallery:${item.id}` : `physical:${item.path}`
}

export function ExplorerWorkbench() {
  const router = useRouter()
  const coarse = useCoarsePointer()
  const urlState = useExplorerUrlState()
  const { node, viewParam, urlKey, refine } = urlState
  const [layout, setLayout] = useState<LayoutMode>('xnview')
  const [view, setView] = useState<ContentView>(() => (viewParam === 'list' ? 'list' : 'grid'))
  // Only the live text of the search box is local; the committed query is the URL's `q`.
  const [searchText, setSearchText] = useState(urlState.q)
  const writtenQueryRef = useRef(urlState.q)
  // A category node already is the category, so a carried-over `cat` must not narrow it.
  const category = node.kind === 'category' ? null : urlState.cat
  const sortField = urlState.sort
  const sortDirection = urlState.dir
  const offset = urlState.offset
  const [querySelection, setQuerySelection] = useState<QuerySelection | null>(null)
  const [metadataOpen, setMetadataOpen] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [organizeOpen, setOrganizeOpen] = useState<'tags' | 'collections' | null>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [menuPoint, setMenuPoint] = useState<{ x: number; y: number } | null>(null)
  const [imageInspect, setImageInspect] = useState<ImageInspectData | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)
  const contentGridRef = useRef<HTMLDivElement | null>(null)
  const contentScrollRef = useRef<HTMLDivElement | null>(null)
  const [contentColumnCount, setContentColumnCount] = useState(1)

  useEffect(() => {
    const device = coarse ? 'mobile' : 'desktop'
    const savedLayout = localStorage.getItem(`explorer_layout_mode:${device}`) as LayoutMode | null
    const savedView = localStorage.getItem(`explorer_content_view:${device}`) as ContentView | null
    if (savedLayout) setLayout(savedLayout)
    if (viewParam === 'grid' || viewParam === 'list') setView(viewParam)
    else if (savedView) setView(savedView)
  }, [coarse, viewParam])

  // The URL changed under us (browser back/forward, node change): follow it.
  useEffect(() => {
    if (urlState.q === writtenQueryRef.current) return
    writtenQueryRef.current = urlState.q
    setSearchText(urlState.q)
  }, [urlState.q])

  useEffect(() => {
    if (searchText === writtenQueryRef.current) return
    const timer = window.setTimeout(() => {
      writtenQueryRef.current = searchText
      refine({ q: searchText, offset: 0 })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [searchText, refine])

  const {
    data: roots,
    error: rootsError,
    isLoading: rootsLoading,
    mutate: mutateRoots,
  } = useSWR('explorer-roots', api.explorer.roots)
  const querySpec = galleryQuery(node, urlState.q, offset, sortField, sortDirection, category)
  const {
    data: galleries,
    error: galleryError,
    isLoading: galleryLoading,
    mutate: mutateGalleries,
  } = useSWR(querySpec ? ['explorer-query', JSON.stringify(querySpec)] : null, () =>
    api.explorer.query(querySpec ?? {}),
  )
  const physicalId = node.kind === 'physical' ? Number(node.id) : 0
  const {
    data: physical,
    error: physicalError,
    isLoading: physicalLoading,
    mutate: mutatePhysical,
  } = useSWR(physicalId ? ['explorer-physical', physicalId, node.path || ''] : null, () =>
    api.explorer.physicalEntries(physicalId, node.path || ''),
  )
  const gallerySource = node.source ?? ''
  const gallerySourceId = node.sourceId ?? ''

  const rootItems = useMemo(() => {
    if (!roots || node.kind !== 'root') return []
    const virtual = roots.virtual.sources.map((source) => ({
      id: -Math.abs(source.id.split('').reduce((value, char) => value + char.charCodeAt(0), 0)),
      source: source.id,
      source_id: source.id,
      title: source.label,
      title_jpn: null,
      category: null,
      language: null,
      artist_id: null,
      uploader: null,
      visibility: 'public' as const,
      pages: source.gallery_count,
      cover_thumb: null,
      logical_bytes: source.logical_bytes,
      unique_cas_bytes: source.unique_cas_bytes,
      is_favorited: false,
      my_rating: null,
      in_reading_list: false,
      deleted_at: null,
    }))
    const physicalRoots: ExplorerPhysicalEntry[] = roots.physical.map((library) => ({
      kind: 'folder',
      name: library.label,
      path: `@library:${library.id}`,
      physical_bytes: library.physical_bytes,
      size_status: library.size_status,
      modified_at: 0,
    }))
    return [...virtual, ...physicalRoots]
  }, [roots, node.kind])

  const contentItems = useMemo<Array<ExplorerGalleryItem | ExplorerPhysicalEntry>>(() => {
    if (node.kind === 'root') return rootItems
    if (node.kind === 'physical') return physical?.entries || []
    return galleries?.items || []
  }, [node.kind, rootItems, physical?.entries, galleries?.items])

  const contentKeys = useMemo(() => contentItems.map(itemKey), [contentItems])
  const selection = useExplorerSelection({
    keys: contentKeys,
    scrollRef: contentScrollRef,
    marqueeEnabled: !coarse,
    toggleOnClick: coarse,
    onMarqueeStart: () => setQuerySelection(null),
    onBackgroundClick: () => setQuerySelection(null),
  })
  const { selectedKeys, clear: clearSelection } = selection
  const selectionModeActive = selectedKeys.size > 0 || querySelection !== null

  useEffect(() => {
    if (!coarse || !selectionModeActive) return
    window.history.pushState({ explorerSelection: true }, '')
    markSelectionEntry()
    const clear = () => {
      clearSelection()
      setQuerySelection(null)
    }
    window.addEventListener('popstate', clear, { once: true })
    return () => window.removeEventListener('popstate', clear)
  }, [coarse, selectionModeActive, clearSelection])

  const { pushNode, stepBack } = urlState
  const navigate = useCallback(
    (next: WorkbenchNode) => {
      clearSelection()
      setQuerySelection(null)
      pushNode(next, view)
    },
    [pushNode, view, clearSelection],
  )

  const nodeKey = `${node.kind}|${node.id ?? ''}|${node.path ?? ''}`
  const previousNodeKeyRef = useRef(nodeKey)
  useEffect(() => {
    if (previousNodeKeyRef.current === nodeKey) return
    previousNodeKeyRef.current = nodeKey
    // A different node starts with no selection and the search box shows that URL's query.
    clearSelection()
    setQuerySelection(null)
    writtenQueryRef.current = urlState.q
    setSearchText(urlState.q)
  }, [nodeKey, urlState.q, clearSelection])

  // A search changes the result set, so a query-wide selection token would act
  // on galleries no longer listed. A page or order change keeps the set (the
  // token stays valid) but moves the visible items, whose keys would otherwise
  // be counted while the actions only send what is on screen.
  const listKey = `${urlState.q}|${offset}|${sortField}|${sortDirection}`
  const previousListRef = useRef({ q: urlState.q, listKey })
  useEffect(() => {
    const previous = previousListRef.current
    if (previous.listKey === listKey) return
    previousListRef.current = { q: urlState.q, listKey }
    clearSelection()
    if (previous.q !== urlState.q) setQuerySelection(null)
  }, [listKey, urlState.q, clearSelection])

  const selectedGalleries = useMemo(
    () =>
      contentItems.filter(
        (item): item is ExplorerGalleryItem =>
          'id' in item && item.id > 0 && selectedKeys.has(itemKey(item)),
      ),
    [contentItems, selectedKeys],
  )
  const selectedPhysicalFolders = useMemo(
    () =>
      contentItems.filter(
        (item): item is ExplorerPhysicalEntry =>
          !('id' in item) && item.kind === 'folder' && selectedKeys.has(itemKey(item)),
      ),
    [contentItems, selectedKeys],
  )
  const selectedItem = contentItems.find((item) => selectedKeys.has(itemKey(item)))
  const physicalRoot = roots?.physical.find(
    (root) => node.kind === 'physical' && String(root.id) === node.id,
  )
  const effectiveSelectedCount = querySelection
    ? querySelection.count - querySelection.excluded.size
    : selectedKeys.size

  const isItemSelected = (item: ExplorerGalleryItem | ExplorerPhysicalEntry) => {
    if (querySelection && 'id' in item && item.id > 0) return !querySelection.excluded.has(item.id)
    return selectedKeys.has(itemKey(item))
  }

  const toggleQueryExclusion = (galleryId: number) => {
    setQuerySelection((current) => {
      if (!current) return current
      const excluded = new Set(current.excluded)
      if (excluded.has(galleryId)) excluded.delete(galleryId)
      else excluded.add(galleryId)
      return { ...current, excluded }
    })
  }

  const selectItem = (
    item: ExplorerGalleryItem | ExplorerPhysicalEntry,
    index: number,
    event?: React.MouseEvent,
  ) => {
    focusIndex(index)
    if (querySelection && 'id' in item && item.id > 0) {
      toggleQueryExclusion(item.id)
      return
    }
    setQuerySelection(null)
    selection.onItemClick(index, event)
  }

  const toggleItem = (item: ExplorerGalleryItem | ExplorerPhysicalEntry, index: number) => {
    focusIndex(index)
    if (querySelection && 'id' in item && item.id > 0) {
      toggleQueryExclusion(item.id)
      return
    }
    setQuerySelection(null)
    selection.toggle(index)
  }

  // Right-click on an unselected item selects only it, like Windows Explorer.
  const openContextMenu = (
    item: ExplorerGalleryItem | ExplorerPhysicalEntry,
    index: number,
    x: number,
    y: number,
  ) => {
    focusIndex(index)
    if (!isItemSelected(item)) {
      setQuerySelection(null)
      selection.selectOnly(index)
    }
    setMenuPoint({ x, y })
  }

  const openItem = (item: ExplorerGalleryItem | ExplorerPhysicalEntry) => {
    if ('id' in item) {
      if (node.kind === 'root' && item.id < 0)
        navigate({ kind: 'source', id: item.source, label: galleryName(item) })
      else
        navigate({
          kind: 'gallery',
          id: String(item.id),
          source: item.source,
          sourceId: item.source_id,
          label: galleryName(item),
        })
      return
    }
    if (item.kind === 'folder') {
      if (item.path.startsWith('@library:')) {
        const id = item.path.split(':')[1]
        const root = roots?.physical.find((value) => String(value.id) === id)
        navigate({ kind: 'physical', id, path: '', label: root?.label })
      } else navigate({ ...node, path: item.path })
    }
  }

  const selectAllQuery = async () => {
    if (!querySpec) return
    try {
      const result = await api.explorer.createSelection(querySpec)
      setQuerySelection({ token: result.selection_token, count: result.count, excluded: new Set() })
      clearSelection()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const deleteSelection = async () => {
    if (!window.confirm(t('explorer.deleteGalleriesConfirm', { count: effectiveSelectedCount })))
      return
    try {
      const result = await api.explorer.deleteSelection(
        querySelection
          ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
          : { gallery_ids: selectedGalleries.map((item) => item.id) },
      )
      toast.success(t('explorer.galleriesDeleted', { count: result.affected }))
      clearSelection()
      setQuerySelection(null)
      await Promise.all([mutateGalleries(), mutateRoots()])
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const actionSelectionBody = querySelection
    ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
    : { gallery_ids: selectedGalleries.map((item) => item.id) }

  const runQuickAction = async (
    action: 'favorite' | 'unfavorite' | 'add_read_later' | 'remove_read_later' | 'rate',
    rating?: number,
  ) => {
    try {
      await api.explorer.bulkAction({ ...actionSelectionBody, action, rating })
      toast.success(t('explorer.bulkActionComplete'))
      await refresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const importSelectedFolder = async () => {
    const folder = selectedPhysicalFolders[0]
    if (!folder || !physicalId) return
    try {
      await api.explorer.importPhysicalFolder(physicalId, folder.path)
      toast.success(t('explorer.importQueued'))
      clearSelection()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    }
  }

  const changeLayout = (next: LayoutMode) => {
    setLayout(next)
    localStorage.setItem(`explorer_layout_mode:${coarse ? 'mobile' : 'desktop'}`, next)
  }
  const changeView = (next: ContentView) => {
    setView(next)
    localStorage.setItem(`explorer_content_view:${coarse ? 'mobile' : 'desktop'}`, next)
    refine({ view: next })
  }

  useEffect(() => {
    if (view === 'list') {
      setContentColumnCount(1)
      return
    }
    const element = contentGridRef.current
    if (!element) return
    const update = () => {
      const columns = window
        .getComputedStyle(element)
        .gridTemplateColumns.split(' ')
        .filter(Boolean).length
      setContentColumnCount(Math.max(1, columns))
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [contentItems.length, layout, view])

  const goBack = useCallback(() => {
    if (node.kind === 'root') return
    let parent: WorkbenchNode = { kind: 'root' }
    if (node.kind === 'physical' && node.path) {
      parent = { ...node, path: node.path.split('/').slice(0, -1).join('/') }
    } else if (node.kind === 'gallery' && node.source) {
      const sourceLabel = roots?.virtual.sources.find((item) => item.id === node.source)?.label
      parent = { kind: 'source', id: node.source, label: sourceLabel ?? node.source }
    }
    stepBack(parent, view)
  }, [node, roots, stepBack, view])

  const keyboardEnabled =
    !coarse && !metadataOpen && !mergeOpen && organizeOpen === null && !shortcutsOpen
  const shortcuts: WorkbenchGlobalShortcuts = {
    onBack: goBack,
    onFocusSearch: () => searchInputRef.current?.focus(),
    onEditMetadata: () => {
      if (querySelection || selectedGalleries.length > 0) setMetadataOpen(true)
    },
    onTreeLayout: () => changeLayout('xnview'),
    onColumnLayout: () => changeLayout('finder'),
    onGridView: () => changeView('grid'),
    onListView: () => changeView('list'),
    onShowShortcuts: () => setShortcutsOpen(true),
    onCyclePane: cycleExplorerPane,
  }
  const { focusedIndex, focusIndex, registerElement } = useWorkbenchKeyboard({
    ...shortcuts,
    itemCount: contentItems.length,
    columnCount: contentColumnCount,
    listMode: view === 'list',
    // The Gallery node's image pane runs its own keyboard handler.
    enabled: keyboardEnabled && node.kind !== 'gallery' && menuPoint === null,
    onOpen: (index) => {
      const item = contentItems[index]
      if (item) openItem(item)
    },
    onToggleSelection: (index) => {
      const item = contentItems[index]
      if (item) toggleItem(item, index)
    },
    onExtendSelection: (fromIndex, toIndex) => {
      setQuerySelection(null)
      selection.extendTo(fromIndex, toIndex)
    },
    onSelectAll: () => {
      if (querySpec) void selectAllQuery()
      else selection.selectAll()
    },
    onClearSelection: () => {
      if (!selectionModeActive) return false
      clearSelection()
      setQuerySelection(null)
      return true
    },
    onDelete: () => {
      if (querySelection || selectedGalleries.length > 0) void deleteSelection()
    },
  })

  const activeItem =
    selectedItem ??
    (node.kind !== 'gallery' && focusedIndex !== null ? contentItems[focusedIndex] : undefined)

  useEffect(() => {
    focusIndex(null)
  }, [focusIndex, node.id, node.kind, node.path])

  const error = rootsError || galleryError || physicalError
  const loading = rootsLoading || galleryLoading || physicalLoading
  useExplorerScrollRestore(
    contentScrollRef,
    urlKey,
    Boolean(roots) && node.kind !== 'gallery' && !loading && contentItems.length > 0,
  )
  const refresh = () => Promise.all([mutateRoots(), mutateGalleries(), mutatePhysical()])

  if (error) {
    return (
      <div className="m-6 rounded-lg border border-red-500/40 bg-red-500/10 p-6 text-red-300">
        <p>{error instanceof Error ? error.message : t('common.errorOccurred')}</p>
        <Button
          variant="secondary"
          size="sm"
          className="mt-4"
          type="button"
          onClick={() => void refresh()}
        >
          {t('common.retry')}
        </Button>
      </div>
    )
  }
  if (!roots && loading)
    return (
      <div className="p-6">
        <SkeletonGrid />
      </div>
    )
  if (!roots) return null

  const hasGallerySelection = Boolean(querySelection) || selectedGalleries.length > 0
  const singleSelected = !querySelection && selectedKeys.size === 1 ? selectedItem : undefined
  const importableFolder =
    selectedPhysicalFolders.length === 1 && !selectedPhysicalFolders[0].gallery_id
  const menuItems: ContextMenuEntry[] = [
    {
      id: 'open',
      label: t('explorer.open'),
      icon: ExternalLink,
      disabled: !singleSelected,
      onSelect: () => {
        if (singleSelected) openItem(singleSelected)
      },
    },
  ]
  if (importableFolder)
    menuItems.push({
      id: 'import',
      label: t('explorer.importFolder'),
      icon: Archive,
      onSelect: () => void importSelectedFolder(),
    })
  if (hasGallerySelection) {
    menuItems.push(
      {
        id: 'metadata',
        label: t('explorer.editMetadata'),
        icon: Edit3,
        separator: true,
        onSelect: () => setMetadataOpen(true),
      },
      {
        id: 'tags',
        label: t('explorer.tags'),
        icon: Tags,
        onSelect: () => setOrganizeOpen('tags'),
      },
      {
        id: 'collections',
        label: t('explorer.collections'),
        icon: Layers3,
        onSelect: () => setOrganizeOpen('collections'),
      },
      {
        id: 'favorite',
        label: t('explorer.favorite'),
        icon: Heart,
        onSelect: () => void runQuickAction('favorite'),
      },
      {
        id: 'read-later',
        label: t('explorer.readLater'),
        icon: Archive,
        onSelect: () => void runQuickAction('add_read_later'),
      },
      {
        id: 'merge',
        label: t('explorer.merge'),
        icon: Merge,
        disabled:
          Boolean(querySelection) || selectedGalleries.length < 2 || selectedGalleries.length > 50,
        onSelect: () => setMergeOpen(true),
      },
      {
        id: 'delete',
        label: t('explorer.deleteFiles'),
        icon: Trash2,
        danger: true,
        separator: true,
        onSelect: () => void deleteSelection(),
      },
    )
  }

  const currentLabel =
    node.kind === 'root'
      ? t('explorer.library')
      : node.kind === 'category'
        ? categoryNodeLabel(node.id)
        : node.label || node.id || t('explorer.library')
  const finderCrumbs: Array<{ label: string; target: WorkbenchNode }> = [
    { label: t('explorer.library'), target: { kind: 'root' } },
  ]
  if (node.kind !== 'root') {
    finderCrumbs.push({ label: currentLabel, target: { ...node, path: '' } })
    if (node.kind === 'physical' && node.path) {
      const parts = node.path.split('/').filter(Boolean)
      parts.forEach((part, index) =>
        finderCrumbs.push({
          label: part,
          target: { ...node, path: parts.slice(0, index + 1).join('/') },
        }),
      )
    }
  }

  return (
    <main className="flex h-[calc(100dvh-7rem-var(--sab)-var(--sat)/2)] min-h-0 flex-col overflow-hidden bg-vault-bg [container-type:inline-size] lg:h-[calc(100dvh-3rem)] lg:min-h-[560px]">
      <header className="flex flex-wrap items-center gap-2 border-b border-vault-border bg-vault-card px-3 py-2">
        <div className="mr-2 flex min-w-0 items-center gap-2">
          <Database size={20} className="text-vault-accent" />
          <h1 className="truncate font-semibold text-vault-text">{t('explorer.workbench')}</h1>
        </div>
        <div className="relative min-w-[180px] flex-1 sm:max-w-md">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-vault-text-muted"
          />
          <input
            ref={searchInputRef}
            aria-keyshortcuts="/"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder={t('explorer.searchPlaceholder')}
            className="w-full rounded-md border border-vault-border bg-vault-bg py-2 pl-9 pr-3 text-sm text-vault-text"
          />
        </div>
        <div
          role="group"
          aria-label={t('explorer.layoutMode')}
          className="hidden rounded-md border border-vault-border p-0.5 sm:flex"
        >
          <button
            type="button"
            aria-label={t('explorer.treeLayout')}
            title={t('explorer.treeLayout')}
            aria-pressed={layout === 'xnview'}
            onClick={() => changeLayout('xnview')}
            className={`rounded p-1.5 ${layout === 'xnview' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:bg-vault-card-hover'}`}
          >
            <FolderTree size={17} />
          </button>
          <button
            type="button"
            aria-label={t('explorer.columnLayout')}
            title={t('explorer.columnLayout')}
            aria-pressed={layout === 'finder'}
            onClick={() => changeLayout('finder')}
            className={`rounded p-1.5 ${layout === 'finder' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:bg-vault-card-hover'}`}
          >
            <Columns3 size={17} />
          </button>
        </div>
        <button
          type="button"
          aria-label={t('explorer.gridView')}
          onClick={() => changeView('grid')}
          className={`rounded p-2 ${view === 'grid' ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text-muted'}`}
        >
          <Grid2X2 size={17} />
        </button>
        <button
          type="button"
          aria-label={t('explorer.listView')}
          onClick={() => changeView('list')}
          className={`rounded p-2 ${view === 'list' ? 'bg-vault-accent/15 text-vault-accent' : 'text-vault-text-muted'}`}
        >
          <List size={18} />
        </button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="hidden sm:inline-flex"
          type="button"
          aria-label={t('explorer.keyboardShortcuts')}
          title={t('explorer.keyboardShortcuts')}
          onClick={() => setShortcutsOpen(true)}
        >
          <Keyboard size={18} />
        </Button>
        <select
          aria-label={t('explorer.libraryTree')}
          value={`${node.kind}:${node.id || ''}`}
          onChange={(event) => {
            const [kind, ...idParts] = event.target.value.split(':')
            const id = idParts.join(':')
            if (kind === 'root') navigate({ kind: 'root' })
            else if (kind === 'trash') navigate({ kind: 'trash', label: t('explorer.trash') })
            else if (kind === 'physical')
              navigate({
                kind: 'physical',
                id,
                label: roots.physical.find((item) => String(item.id) === id)?.label,
              })
            else if (kind === 'category')
              navigate({ kind: 'category', id, label: categoryNodeLabel(id) })
            else navigate({ kind: kind as WorkbenchNode['kind'], id })
          }}
          className="w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text lg:hidden"
        >
          <option value="root:">{t('explorer.library')}</option>
          <optgroup label={t('explorer.sources')}>
            {roots.virtual.sources.map((item) => (
              <option key={item.id} value={`source:${item.id}`}>
                {item.label}
              </option>
            ))}
          </optgroup>
          <optgroup label={t('explorer.collections')}>
            {roots.virtual.collections.items.map((item) => (
              <option key={item.id} value={`collection:${item.id}`}>
                {item.name}
              </option>
            ))}
          </optgroup>
          <optgroup label={t('explorer.artists')}>
            {roots.virtual.artists.items.map((item) => (
              <option key={item.id} value={`artist:${item.id}`}>
                {item.name.replace(/^[^:]+:/, '')}
              </option>
            ))}
          </optgroup>
          <optgroup label={t('explorer.savedSearches')}>
            {roots.virtual.saved_searches.items.map((item) => (
              <option key={item.id} value={`saved_search:${item.id}`}>
                {item.name}
              </option>
            ))}
          </optgroup>
          {roots.virtual.categories && (
            <optgroup label={t('explorer.categories')}>
              <option value={`category:${UNCATEGORIZED_ID}`}>
                {t('explorer.uncategorized')} ({roots.virtual.categories.uncategorized})
              </option>
              {roots.virtual.categories.items.map((item) => (
                <option key={item.id} value={`category:${item.id}`}>
                  {item.label} ({item.gallery_count})
                </option>
              ))}
            </optgroup>
          )}
          <optgroup label={t('explorer.smartViews')}>
            <option value="smart:missing_metadata">{t('explorer.missingMetadata')}</option>
            <option value="smart:duplicates">{t('explorer.duplicates')}</option>
            <option value="smart:hidden_images">{t('explorer.hiddenImages')}</option>
            <option value="trash:">{t('explorer.trash')}</option>
          </optgroup>
          {roots.physical.length > 0 && (
            <optgroup label={t('explorer.physicalLibraries')}>
              {roots.physical.map((item) => (
                <option key={item.id} value={`physical:${item.id}`}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </header>

      {layout === 'finder' && (
        <div className="hidden items-stretch border-b border-vault-border bg-vault-card/50 lg:flex">
          {finderCrumbs.map((crumb, index) => (
            <button
              key={`${crumb.label}-${index}`}
              type="button"
              onClick={() => navigate(crumb.target)}
              className="flex min-w-[180px] items-center justify-between border-r border-vault-border px-4 py-2 text-sm text-vault-text"
            >
              <span className="truncate">{crumb.label}</span>
              <ChevronRight size={14} />
            </button>
          ))}
        </div>
      )}

      <div
        className={`min-h-0 flex-1 overflow-hidden ${layout === 'xnview' ? 'lg:grid lg:grid-cols-[260px_minmax(0,1fr)_300px]' : 'lg:grid lg:grid-cols-[420px_minmax(0,1fr)_300px]'}`}
      >
        <div className="hidden min-h-0 lg:block">
          {layout === 'xnview' ? (
            <NavigationTree roots={roots} node={node} navigate={navigate} />
          ) : (
            <FinderColumns roots={roots} node={node} navigate={navigate} />
          )}
        </div>
        <section
          data-explorer-content-pane
          className="flex h-full min-h-0 flex-col overflow-hidden"
        >
          <div className="flex items-center gap-2 border-b border-vault-border px-4 py-2 text-sm">
            {node.kind !== 'root' && (
              <button type="button" onClick={goBack} className="text-vault-accent">
                {t('explorer.backToRoot')}
              </button>
            )}
            <FolderOpen size={16} className="text-vault-text-muted" />
            <span className="truncate font-medium text-vault-text">
              {currentLabel}
              {node.path ? ` / ${node.path}` : ''}
            </span>
            <span className="ml-auto text-xs text-vault-text-muted">
              {node.kind === 'physical'
                ? (physical?.total ?? 0)
                : node.kind === 'root'
                  ? rootItems.length
                  : (galleries?.total ?? imageInspect?.summary.active_count ?? 0)}
            </span>
            {querySpec && (
              <>
                <select
                  aria-label={t('explorer.sortBy')}
                  value={sortField}
                  onChange={(event) =>
                    refine({
                      sort: event.target.value as NonNullable<ExplorerQuery['sort']>,
                      offset: 0,
                    })
                  }
                  className="rounded-md border border-vault-border bg-vault-bg px-2 py-1 text-xs text-vault-text"
                >
                  <option value="added_at">{t('explorer.sortAdded')}</option>
                  <option value="content_updated_at">{t('explorer.sortUpdated')}</option>
                  <option value="posted_at">{t('explorer.sortPosted')}</option>
                  <option value="title">{t('explorer.sortTitle')}</option>
                  <option value="rating">{t('explorer.sortRating')}</option>
                  <option value="pages">{t('explorer.sortPages')}</option>
                  <option value="size">{t('explorer.sortSize')}</option>
                </select>
                {node.kind !== 'category' && (
                  <CategoryFilter
                    value={category}
                    counts={galleries?.category_counts}
                    onChange={(next) => {
                      refine({ cat: next, offset: 0 })
                      clearSelection()
                      setQuerySelection(null)
                    }}
                  />
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  className="text-xs"
                  type="button"
                  aria-label={t('explorer.sortDirection')}
                  title={
                    sortDirection === 'asc'
                      ? t('explorer.sortAscending')
                      : t('explorer.sortDescending')
                  }
                  onClick={() =>
                    refine({ dir: sortDirection === 'asc' ? 'desc' : 'asc', offset: 0 })
                  }
                >
                  {sortDirection === 'asc' ? '↑' : '↓'}
                </Button>
              </>
            )}
            {querySpec && (galleries?.total || 0) > 0 && (
              <Button
                variant="secondary"
                size="sm"
                className="text-xs"
                type="button"
                onClick={selectAllQuery}
              >
                {t('explorer.selectAllResults')}
              </Button>
            )}
            {node.kind === 'smart' && node.id === 'duplicates' && (
              <Button
                variant="secondary"
                size="sm"
                className="text-xs"
                type="button"
                onClick={() => router.push('/dedup')}
              >
                {t('explorer.reviewPairs')}
              </Button>
            )}
            {node.kind === 'physical' && (
              <Button
                variant="ghost"
                size="icon-sm"
                type="button"
                aria-label={t('explorer.refreshSize')}
                onClick={async () => {
                  await api.explorer.refreshPhysicalSize(physicalId, node.path || '')
                  await mutatePhysical()
                }}
              >
                <RefreshCw size={15} />
              </Button>
            )}
          </div>

          {layout === 'finder' && activeItem && (
            <div className="hidden h-[42%] min-h-[240px] items-center justify-center border-b border-vault-border bg-black/20 p-5 lg:flex">
              {'id' in activeItem ? (
                activeItem.cover_thumb ? (
                  <AppImage
                    src={activeItem.cover_thumb}
                    alt=""
                    className="h-full max-w-full object-contain"
                  />
                ) : (
                  <Folder size={80} strokeWidth={1} className="text-vault-text-muted" />
                )
              ) : activeItem.kind === 'media' ? (
                /\.(mp4|webm)$/i.test(activeItem.name) ? (
                  <video
                    controls
                    src={api.explorer.physicalPreviewUrl(physicalId, activeItem.path)}
                    className="h-full max-w-full"
                  />
                ) : (
                  <img
                    src={api.explorer.physicalPreviewUrl(physicalId, activeItem.path)}
                    alt={activeItem.name}
                    className="h-full max-w-full object-contain"
                  />
                )
              ) : (
                <Folder size={80} strokeWidth={1} className="text-vault-text-muted" />
              )}
            </div>
          )}

          {node.kind === 'gallery' ? (
            <GalleryImagePane
              galleryId={Number(node.id) || 0}
              source={gallerySource}
              sourceId={gallerySourceId}
              view={view}
              coarse={coarse}
              keyboardEnabled={keyboardEnabled}
              shortcuts={shortcuts}
              onOpenImage={(image) => {
                saveExplorerScroll()
                router.push(readerHref(gallerySource, gallerySourceId, image.page_num || undefined))
              }}
              onChanged={() => void mutateRoots()}
              onInspect={setImageInspect}
            />
          ) : (
            <div
              ref={contentScrollRef}
              onPointerDown={selection.onContainerPointerDown}
              className="relative min-h-0 flex-1 select-none overflow-y-auto pb-24 lg:pb-4"
            >
              {loading ? (
                <div className="p-4">
                  <SkeletonGrid />
                </div>
              ) : contentItems.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-vault-text-muted">
                  <Folder size={42} strokeWidth={1.2} />
                  <p>{t('explorer.emptyDir')}</p>
                </div>
              ) : view === 'grid' ? (
                <div
                  ref={contentGridRef}
                  className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
                >
                  {contentItems.map((item, index) => (
                    <SelectableCard
                      key={itemKey(item)}
                      item={item}
                      selected={isItemSelected(item)}
                      selectionMode={selectedKeys.size > 0 || Boolean(querySelection)}
                      coarse={coarse}
                      view={view}
                      previewUrl={
                        'id' in item || item.kind !== 'media'
                          ? undefined
                          : api.explorer.physicalPreviewUrl(physicalId, item.path)
                      }
                      elementRef={(element) => {
                        registerElement(index, element)
                        selection.registerItem(itemKey(item), element)
                      }}
                      tabIndex={
                        focusedIndex === null
                          ? index === 0
                            ? 0
                            : -1
                          : focusedIndex === index
                            ? 0
                            : -1
                      }
                      focused={focusedIndex === index}
                      onFocus={() => focusIndex(index)}
                      onSelect={(event) => selectItem(item, index, event)}
                      onToggle={() => toggleItem(item, index)}
                      onOpen={() => openItem(item)}
                      onContextMenuAt={(x, y) => openContextMenu(item, index, x, y)}
                    />
                  ))}
                </div>
              ) : (
                <div ref={contentGridRef}>
                  {contentItems.map((item, index) => (
                    <SelectableCard
                      key={itemKey(item)}
                      item={item}
                      selected={isItemSelected(item)}
                      selectionMode={selectedKeys.size > 0 || Boolean(querySelection)}
                      coarse={coarse}
                      view={view}
                      previewUrl={
                        'id' in item || item.kind !== 'media'
                          ? undefined
                          : api.explorer.physicalPreviewUrl(physicalId, item.path)
                      }
                      elementRef={(element) => {
                        registerElement(index, element)
                        selection.registerItem(itemKey(item), element)
                      }}
                      tabIndex={
                        focusedIndex === null
                          ? index === 0
                            ? 0
                            : -1
                          : focusedIndex === index
                            ? 0
                            : -1
                      }
                      focused={focusedIndex === index}
                      onFocus={() => focusIndex(index)}
                      onSelect={(event) => selectItem(item, index, event)}
                      onToggle={() => toggleItem(item, index)}
                      onOpen={() => openItem(item)}
                      onContextMenuAt={(x, y) => openContextMenu(item, index, x, y)}
                    />
                  ))}
                </div>
              )}
              {querySpec && galleries && galleries.total > galleries.limit && (
                <div className="flex items-center justify-center gap-3 p-4">
                  <Button
                    variant="secondary"
                    size="sm"
                    type="button"
                    disabled={offset === 0}
                    onClick={() => refine({ offset: Math.max(0, offset - galleries.limit) })}
                  >
                    {t('common.prev')}
                  </Button>
                  <span className="text-sm text-vault-text-muted">
                    {offset + 1}–{Math.min(offset + galleries.limit, galleries.total)} /{' '}
                    {galleries.total}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    type="button"
                    disabled={offset + galleries.limit >= galleries.total}
                    onClick={() => refine({ offset: offset + galleries.limit })}
                  >
                    {t('common.next')}
                  </Button>
                </div>
              )}
              <SelectionMarquee rect={selection.marquee} />
            </div>
          )}
        </section>
        <div className="hidden min-h-0 lg:block">
          {node.kind === 'gallery' ? (
            <ImageInspector data={imageInspect} />
          ) : (
            <Inspector item={activeItem} physicalRoot={physicalRoot} />
          )}
        </div>
      </div>

      {effectiveSelectedCount > 0 && (
        <div className="fixed inset-x-2 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-50 flex max-w-[calc(100vw-1rem)] items-center gap-1 overflow-x-auto rounded-xl border border-vault-border bg-vault-card p-2 shadow-2xl lg:inset-x-auto lg:bottom-5 lg:left-1/2 lg:-translate-x-1/2">
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            onClick={() => {
              clearSelection()
              setQuerySelection(null)
            }}
          >
            <X size={18} />
          </Button>
          <span className="mr-2 whitespace-nowrap text-sm font-medium text-vault-text">
            {t('explorer.selectedCount', { count: effectiveSelectedCount })}
          </span>
          {selectedPhysicalFolders.length === 1 && !selectedPhysicalFolders[0].gallery_id && (
            <Button variant="ghost" size="sm" type="button" onClick={importSelectedFolder}>
              <Archive size={16} />
              <span className="hidden sm:inline">{t('explorer.importFolder')}</span>
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            type="button"
            disabled={!querySelection && selectedGalleries.length === 0}
            onClick={() => setMetadataOpen(true)}
          >
            <Edit3 size={16} />
            <span className="hidden sm:inline">{t('explorer.editMetadata')}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            disabled={
              Boolean(querySelection) ||
              selectedGalleries.length < 2 ||
              selectedGalleries.length > 50
            }
            onClick={() => setMergeOpen(true)}
          >
            <Merge size={16} />
            <span className="hidden sm:inline">{t('explorer.merge')}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            disabled={!querySelection && selectedGalleries.length === 0}
            onClick={() => setOrganizeOpen('tags')}
          >
            <Tags size={16} />
            <span className="hidden sm:inline">{t('explorer.tags')}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            disabled={!querySelection && selectedGalleries.length === 0}
            onClick={() => setOrganizeOpen('collections')}
          >
            <Layers3 size={16} />
            <span className="hidden sm:inline">{t('explorer.collections')}</span>
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            disabled={!querySelection && selectedGalleries.length === 0}
            onClick={() => void runQuickAction('favorite')}
            aria-label={t('explorer.favorite')}
          >
            <Heart size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            disabled={!querySelection && selectedGalleries.length === 0}
            onClick={() => void runQuickAction('add_read_later')}
            aria-label={t('explorer.readLater')}
          >
            <Archive size={16} />
          </Button>
          <select
            aria-label={t('explorer.rating')}
            disabled={!querySelection && selectedGalleries.length === 0}
            defaultValue=""
            onChange={(event) => {
              if (event.target.value) void runQuickAction('rate', Number(event.target.value))
              event.target.value = ''
            }}
            className="hidden rounded-md border border-vault-border bg-vault-card px-2 py-1 text-sm text-vault-text sm:block disabled:opacity-30"
          >
            <option value="">{t('explorer.rating')}</option>
            {[0, 1, 2, 3, 4, 5].map((rating) => (
              <option key={rating} value={rating}>
                {rating}
              </option>
            ))}
          </select>
          <select
            aria-label={t('explorer.moreActions')}
            disabled={!querySelection && selectedGalleries.length === 0}
            defaultValue=""
            onChange={(event) => {
              const action = event.target.value as 'unfavorite' | 'remove_read_later'
              if (action) void runQuickAction(action)
              event.target.value = ''
            }}
            className="rounded-md border border-vault-border bg-vault-card px-2 py-1 text-sm text-vault-text disabled:opacity-30"
          >
            <option value="">{t('explorer.moreActions')}</option>
            <option value="unfavorite">{t('explorer.unfavorite')}</option>
            <option value="remove_read_later">{t('explorer.removeReadLater')}</option>
          </select>
          <Button
            variant="ghost"
            size="sm"
            className="text-red-400 hover:bg-red-500/10"
            type="button"
            disabled={!querySelection && selectedGalleries.length === 0}
            onClick={deleteSelection}
          >
            <Trash2 size={16} />
            <span className="hidden sm:inline">{t('explorer.deleteFiles')}</span>
          </Button>
        </div>
      )}

      {menuPoint && (
        <ContextMenu
          x={menuPoint.x}
          y={menuPoint.y}
          items={menuItems}
          ariaLabel={t('explorer.contextMenu')}
          onClose={() => setMenuPoint(null)}
        />
      )}
      {metadataOpen && (
        <MetadataDialog
          selection={selectedGalleries}
          querySelection={querySelection}
          onClose={() => setMetadataOpen(false)}
          onDone={() => void refresh()}
        />
      )}
      {mergeOpen && (
        <MergeDialog
          selection={selectedGalleries}
          onClose={() => setMergeOpen(false)}
          onDone={() => void refresh()}
        />
      )}
      {organizeOpen && (
        <OrganizeDialog
          kind={organizeOpen}
          selectionBody={actionSelectionBody}
          onClose={() => setOrganizeOpen(null)}
          onDone={() => void refresh()}
        />
      )}
      {shortcutsOpen && (
        <Modal title={t('explorer.keyboardShortcuts')} onClose={() => setShortcutsOpen(false)}>
          <div className="grid gap-2 p-5 text-sm">
            {[
              ['↑ ↓ ← → · Home · End', t('explorer.navigateItems')],
              ['Enter', t('explorer.openItem')],
              ['Space', t('explorer.toggleSelection')],
              ['Shift + ↑ ↓ ← →', t('explorer.extendSelection')],
              ['Ctrl/⌘ + A', t('explorer.selectAllResults')],
              ['Esc', t('explorer.clearSelection')],
              ['Backspace', t('explorer.back')],
              ['/ · Ctrl/⌘ + K', t('explorer.focusSearch')],
              ['Delete · ⌘ + Backspace', t('explorer.deleteFiles')],
              ['Delete', t('explorer.hideImagesInGallery')],
              ['Shift + Delete', t('explorer.purgeImages')],
              ['Ctrl/⌘ + Click', t('explorer.toggleSelection')],
              ['Shift + Click', t('explorer.extendSelection')],
              ['Drag', t('explorer.marqueeSelect')],
              ['Right-click · Shift + F10', t('explorer.contextMenu')],
              ['F2', t('explorer.editMetadata')],
              ['Alt + 1 / 2', t('explorer.switchLayout')],
              ['Ctrl/⌘ + 1 / 2', t('explorer.switchView')],
              ['F6', t('explorer.cyclePane')],
            ].map(([keys, label]) => (
              <div
                key={keys}
                className="flex items-center justify-between gap-5 rounded border border-vault-border px-3 py-2"
              >
                <span className="text-vault-text-muted">{label}</span>
                <kbd className="whitespace-nowrap rounded bg-vault-bg px-2 py-1 font-mono text-xs text-vault-text">
                  {keys}
                </kbd>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </main>
  )
}
