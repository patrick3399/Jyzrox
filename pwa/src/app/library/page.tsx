'use client'

import { useState, useCallback, Suspense, useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { BookOpen, X, Bookmark, BookmarkCheck, HelpCircle } from 'lucide-react'
import { useGalleryCategories, useLibrarySources } from '@/hooks/useGalleries'
import { useCategoryRegistry } from '@/hooks/useCategoryRegistry'
import type { Gallery } from '@/lib/types'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useLibraryBrowseSession } from '@/hooks/useLibraryBrowseSession'
import { useCollections } from '@/hooks/useCollections'
import { useAddDatasetMembers, useDatasets } from '@/hooks/useDatasets'
import { useProfile } from '@/hooks/useProfile'
import { useUnifiedSearch } from '@/hooks/useUnifiedSearch'
import { LibraryGalleryCard } from '@/components/GalleryCard'
import { GalleryListCard } from '@/components/GalleryListCard'
import { SkeletonGrid } from '@/components/Skeleton'
import { LibrarySearchBar } from '@/components/library/LibrarySearchBar'
import { LibraryViewControls } from '@/components/library/LibraryViewControls'
import { LibraryFilterChips } from '@/components/library/LibraryFilterChips'
import { EmptyState } from '@/components/EmptyState'
import { VirtualGrid } from '@/components/VirtualGrid'
import { t, formatNumber } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { galleryHref } from '@/lib/galleryRoutes'
import type { SearchGalleryItem } from '@/lib/api'
import { decideAnchorRestore, restoreAnchorOffset, type BrowseAnchor } from '@/lib/browse/anchor'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'
import {
  estimateLibraryGridRowHeight,
  getLibraryGridGap,
  resolveLibraryGrid,
} from '@/lib/libraryLayout'
import { saveLibraryDensityOverride, type GridDensityPreference } from '@/lib/uiPreferences'
import { libraryFilterChips, type LibraryFilterChipKey } from '@/lib/libraryFilterChips'
import { useDisplayPreferences } from '@/hooks/useDisplayPreferences'
import { useLibraryDensityOverride } from '@/hooks/useLibraryDensityOverride'
import { useScrollReveal } from '@/hooks/useScrollReveal'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { useOpenedOnce } from '@/hooks/useOpenedOnce'
import dynamic from 'next/dynamic'

// Batch-bar overlays only exist in select mode; keep Base UI Dialog out of the
// page's initial JS.
const Dialog = dynamic(() => import('@/components/ui/dialog').then((module) => module.Dialog), {
  ssr: false,
})
const AddToCollectionMenu = dynamic(
  () =>
    import('@/components/library/AddToCollectionMenu').then((module) => module.AddToCollectionMenu),
  { ssr: false },
)

const VIEW_MODE_KEY = 'library_view_mode'
const LAYOUT_SWITCH_WATCHDOG_MS = 2000
// Gap between the sticky search block and the card a layout switch lands on.
const LAYOUT_SWITCH_GAP_PX = 8

function loadViewMode(): 'grid' | 'list' {
  if (typeof window === 'undefined') return 'grid'
  try {
    return localStorage.getItem(VIEW_MODE_KEY) === 'list' ? 'list' : 'grid'
  } catch {
    return 'grid'
  }
}

const SORT_OPTIONS = [
  { value: 'added_at', label: () => t('library.dateAdded') },
  { value: 'content_updated_at', label: () => t('library.dateUpdated') },
  { value: 'posted_at', label: () => t('library.datePosted') },
  { value: 'rating', label: () => t('library.rating') },
  { value: 'pages', label: () => t('library.pagesSort') },
  { value: 'title', label: () => t('library.titleSort') },
] as const

function mapSearchItemToGallery(item: SearchGalleryItem): Gallery {
  return {
    id: item.id,
    title: item.title,
    title_jpn: item.title_jpn ?? '',
    source: item.source,
    source_id: item.source_id,
    category: item.category ?? '',
    language: item.language ?? '',
    pages: item.pages,
    rating: item.rating,
    favorited: item.favorited,
    is_favorited: item.is_favorited,
    my_rating: item.my_rating,
    in_reading_list: item.in_reading_list,
    uploader: item.uploader ?? '',
    artist_id: item.artist_id,
    artist_name: item.artist_name,
    download_status: item.download_status as Gallery['download_status'],
    added_at: item.added_at ?? '',
    posted_at: item.posted_at,
    content_updated_at: item.content_updated_at ?? null,
    tags_array: item.tags_array ?? item.tags,
    cover_thumb: item.cover_thumb ?? null,
    import_mode: item.import_mode,
    source_url: item.source_url,
  }
}

function LibraryContent() {
  const router = useRouter()

  const {
    rawQuery,
    inputValue,
    parsed,
    setFilter,
    commitSearch,
    clearSearch,
    clearFilters,
    handleInputChange,
    selectMode,
    setSelectMode,
    selectedIds,
    setSelectedIds,
  } = useUnifiedSearch()

  const { data: categoriesData } = useGalleryCategories()
  const { data: categoryRegistry } = useCategoryRegistry()
  const { data: sourcesData } = useLibrarySources()

  const [colCount, setColCount] = useState(4)
  const [batchTagMode, setBatchTagMode] = useState<'add' | 'remove' | null>(null)
  const [batchTagInput, setBatchTagInput] = useState('')
  const batchTagInputRef = useRef<HTMLInputElement>(null)
  const batchTagOpened = useOpenedOnce(batchTagMode !== null)
  const [batchTagList, setBatchTagList] = useState<string[]>([])
  const [filterPanelOpen, setFilterPanelOpen] = useState(false)
  // Search block: sticky, slides away on scroll down and back on scroll up.
  const [searchFocused, setSearchFocused] = useState(false)
  const searchSentinelRef = useRef<HTMLDivElement>(null)
  const searchBlockRef = useRef<HTMLDivElement>(null)
  const [viewMenuOpen, setViewMenuOpen] = useState(false)
  // A layout switch waiting to land on its anchor card keeps the bar revealed.
  const [layoutSwitch, setLayoutSwitch] = useState<{ key: string; itemId: number } | undefined>()
  const {
    stuck: searchStuck,
    hidden: searchHidden,
    rebase: rebaseScrollReveal,
  } = useScrollReveal({
    sentinelRef: searchSentinelRef,
    blockRef: searchBlockRef,
    locked: searchFocused || filterPanelOpen || viewMenuOpen || layoutSwitch !== undefined,
  })
  const [syntaxHelpOpen, setSyntaxHelpOpen] = useState(false)
  const displayPreferences = useDisplayPreferences()
  const densityOverride = useLibraryDensityOverride()
  const { density: gridDensity, columns: gridColumns } = useMemo(
    () => resolveLibraryGrid(displayPreferences, densityOverride),
    [displayPreferences, densityOverride],
  )

  // View mode: 'grid' | 'list', persisted to localStorage
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(loadViewMode)

  // Collections stay eager because they also populate the normal filter panel.
  const { data: collectionsData } = useCollections()
  const { data: profile } = useProfile()
  const {
    state,
    loadMore,
    refresh,
    retry,
    checkpoint,
    updateView,
    restoreInstruction,
    acknowledgeRestore,
  } = useLibraryBrowseSession({
    query: rawQuery,
    enabled: profile !== undefined,
    userId: profile?.username,
  })
  const canManageDatasets = profile?.role === 'member' || profile?.role === 'admin'
  // Datasets are only ever read by the batch-action bar, so don't pay for the
  // request until that bar is actually on screen.
  const batchActionsVisible = selectMode && selectedIds.size > 0
  const { data: datasetsData } = useDatasets(canManageDatasets && batchActionsVisible)
  const { trigger: addDatasetMembers } = useAddDatasetMembers()

  // Derive sort from parsed filters (default 'added_at')
  const sortValue = parsed.sort ?? 'added_at'

  // Derive combined source filter for the dropdown (source + import_mode → "local:link")
  const combinedSource = parsed.source
    ? parsed.importMode
      ? `${parsed.source}:${parsed.importMode}`
      : parsed.source
    : ''

  const sourceDisplayLabel = (value: string, fallback: string) =>
    value === 'local:link'
      ? t('explorer.externalFolders')
      : value === 'local:copy'
        ? t('explorer.jyzroxImport')
        : fallback

  const filterChips = libraryFilterChips(parsed, {
    sourceLabel: (combined) =>
      sourceDisplayLabel(
        combined,
        sourcesData?.find((opt) => opt.value === combined)?.label ?? combined,
      ),
    collectionName: (id) => collectionsData?.collections.find((c) => c.id === id)?.name,
    sortLabel: (value) => SORT_OPTIONS.find((opt) => opt.value === value)?.label() ?? value,
  })

  const handleRemoveChip = (key: LibraryFilterChipKey) => {
    setFilter(key, null)
    if (key === 'source') setFilter('import', null)
  }

  const displayGalleries = useMemo<Gallery[]>(
    () => state.items.map(mapSearchItemToGallery),
    [state.items],
  )
  const total = state.total
  const error = state.error
  const isSessionLoading = state.status === 'loading'
  const itemElementsRef = useRef(new Map<number, HTMLElement>())
  const visibleStartRef = useRef(0)
  const layoutRef = useRef<BrowseLayoutSnapshot>({ columns: 4, width: 0, mode: viewMode })
  const pendingRestoreRef = useRef<{
    key: string
    identityKey: string
    index: number
    offset: number
  } | null>(null)
  const liveViewRef = useRef<{
    anchor: BrowseAnchor | null
    layout: BrowseLayoutSnapshot | null
  } | null>(null)
  // Layout switches land through their own channel: the session-restore effect
  // below clears `pendingRestoreRef` whenever `displayGalleries` changes with no
  // instruction, which would drop a switch that overlaps an append.
  const pendingLayoutSwitchRef = useRef<{
    key: string
    itemId: number
    anchor: BrowseAnchor
  } | null>(null)
  const layoutSwitchCounterRef = useRef(0)
  const previousIdentityRef = useRef(state.identityKey)
  const handledRestoreKeyRef = useRef<string | null>(null)
  const scheduledRestoreKeyRef = useRef<string | null>(null)
  const [restoreRequest, setRestoreRequest] = useState<{
    key: string
    identityKey: string
    index: number
  }>()

  const clearLayoutSwitch = useCallback(() => {
    pendingLayoutSwitchRef.current = null
    setLayoutSwitch(undefined)
  }, [])

  useEffect(() => {
    if (previousIdentityRef.current === state.identityKey) return
    previousIdentityRef.current = state.identityKey
    pendingRestoreRef.current = null
    liveViewRef.current = null
    clearLayoutSwitch()
    setRestoreRequest(undefined)
  }, [clearLayoutSwitch, state.identityKey])

  // The request's index is derived here rather than stored: child effects run
  // before this component's effects, so an index kept from before a refresh
  // could land on a different card.
  const layoutSwitchIndex = useMemo(
    () =>
      layoutSwitch ? displayGalleries.findIndex((gallery) => gallery.id === layoutSwitch.itemId) : -1,
    [displayGalleries, layoutSwitch],
  )
  const layoutSwitchRequest = useMemo(
    () =>
      layoutSwitch && layoutSwitchIndex >= 0
        ? { key: layoutSwitch.key, index: layoutSwitchIndex }
        : undefined,
    [layoutSwitch, layoutSwitchIndex],
  )
  const layoutSwitchKey = layoutSwitch?.key
  const layoutSwitchGone = layoutSwitchKey !== undefined && layoutSwitchIndex < 0

  useEffect(() => {
    if (layoutSwitchGone) clearLayoutSwitch()
  }, [clearLayoutSwitch, layoutSwitchGone])

  // iOS can queue the virtualizer's scroll during a fling, and a user takeover
  // cancels it; the token is already issued, so without this the bar and the
  // scroll capture would stay blocked.
  useEffect(() => {
    if (layoutSwitchKey === undefined) return
    const timer = setTimeout(clearLayoutSwitch, LAYOUT_SWITCH_WATCHDOG_MS)
    window.addEventListener('touchstart', clearLayoutSwitch, { passive: true })
    window.addEventListener('wheel', clearLayoutSwitch, { passive: true })
    return () => {
      clearTimeout(timer)
      window.removeEventListener('touchstart', clearLayoutSwitch)
      window.removeEventListener('wheel', clearLayoutSwitch)
    }
  }, [clearLayoutSwitch, layoutSwitchKey])

  useEffect(() => {
    if (!restoreInstruction || restoreInstruction.identityKey !== state.identityKey) {
      if (pendingRestoreRef.current) {
        pendingRestoreRef.current = null
        setRestoreRequest(undefined)
      }
      return
    }
    if (handledRestoreKeyRef.current === restoreInstruction.key) return
    if (restoreInstruction.target.kind === 'top') {
      if (pendingRestoreRef.current) {
        pendingRestoreRef.current = null
        setRestoreRequest(undefined)
      }
      if (scheduledRestoreKeyRef.current === restoreInstruction.key) return
      scheduledRestoreKeyRef.current = restoreInstruction.key
      const frame = requestAnimationFrame(() => {
        window.scrollTo(0, 0)
        handledRestoreKeyRef.current = restoreInstruction.key
        scheduledRestoreKeyRef.current = null
        acknowledgeRestore(restoreInstruction.key)
      })
      return () => {
        cancelAnimationFrame(frame)
        if (scheduledRestoreKeyRef.current === restoreInstruction.key)
          scheduledRestoreKeyRef.current = null
      }
    }
    const anchor = restoreInstruction.target.view.anchor
    if (!anchor) {
      if (pendingRestoreRef.current) {
        pendingRestoreRef.current = null
        setRestoreRequest(undefined)
      }
      if (scheduledRestoreKeyRef.current === restoreInstruction.key) return
      scheduledRestoreKeyRef.current = restoreInstruction.key
      const frame = requestAnimationFrame(() => {
        window.scrollTo(0, 0)
        handledRestoreKeyRef.current = restoreInstruction.key
        scheduledRestoreKeyRef.current = null
        acknowledgeRestore(restoreInstruction.key)
      })
      return () => {
        cancelAnimationFrame(frame)
        if (scheduledRestoreKeyRef.current === restoreInstruction.key)
          scheduledRestoreKeyRef.current = null
      }
    }
    const decision = decideAnchorRestore(anchor, displayGalleries, (gallery) => gallery.id)
    if (decision.kind === 'anchor') {
      const nextPending = {
        key: restoreInstruction.key,
        identityKey: state.identityKey,
        index: decision.index,
        offset: decision.offset,
      }
      const pending = pendingRestoreRef.current
      if (
        pending?.key === nextPending.key &&
        pending.identityKey === nextPending.identityKey &&
        pending.index === nextPending.index &&
        pending.offset === nextPending.offset
      )
        return
      pendingRestoreRef.current = nextPending
      setRestoreRequest({
        key: restoreInstruction.key,
        identityKey: state.identityKey,
        index: decision.index,
      })
      return
    }
    if (pendingRestoreRef.current) {
      pendingRestoreRef.current = null
      setRestoreRequest(undefined)
    }
    if (scheduledRestoreKeyRef.current === restoreInstruction.key) return
    scheduledRestoreKeyRef.current = restoreInstruction.key
    const frame = requestAnimationFrame(() => {
      window.scrollTo(0, decision.kind === 'pixel' ? decision.scrollY : 0)
      handledRestoreKeyRef.current = restoreInstruction.key
      scheduledRestoreKeyRef.current = null
      acknowledgeRestore(restoreInstruction.key)
    })
    return () => {
      cancelAnimationFrame(frame)
      if (scheduledRestoreKeyRef.current === restoreInstruction.key)
        scheduledRestoreKeyRef.current = null
    }
  }, [acknowledgeRestore, displayGalleries, restoreInstruction, state.identityKey])

  const captureAnchor = useCallback(
    (preferred?: Gallery): BrowseAnchor => {
      const fallbackIndex = Math.min(
        visibleStartRef.current,
        Math.max(0, displayGalleries.length - 1),
      )
      const gallery = preferred ?? displayGalleries[fallbackIndex]
      const element = gallery ? itemElementsRef.current.get(gallery.id) : null
      return {
        itemId: gallery?.id ?? null,
        offset: element?.getBoundingClientRect().top ?? 0,
        scrollY: window.scrollY,
      }
    },
    [displayGalleries],
  )

  const openGallery = useCallback(
    (gallery: Gallery) => {
      checkpoint({ anchor: captureAnchor(gallery), layout: layoutRef.current })
      router.push(galleryHref(gallery.source, gallery.source_id))
    },
    [captureAnchor, checkpoint, router],
  )

  // `captureAnchor` is rebuilt whenever the gallery list changes, so the scroll
  // subscription below must not depend on it directly: an append that commits
  // before a scheduled capture frame fires would tear the effect down, cancel the
  // frame, and drop that scroll position without rescheduling it. Infinite scroll
  // makes that window routine, since scrolling is what triggers the append.
  const captureAnchorRef = useRef(captureAnchor)
  useLayoutEffect(() => {
    captureAnchorRef.current = captureAnchor
  }, [captureAnchor])

  useLayoutEffect(() => {
    let frame: number | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    const save = () => {
      const view = liveViewRef.current ?? {
        anchor: captureAnchorRef.current(),
        layout: layoutRef.current,
      }
      checkpoint(view)
    }
    const capture = () => {
      frame = undefined
      if (pendingRestoreRef.current || pendingLayoutSwitchRef.current) return
      const view = { anchor: captureAnchorRef.current(), layout: layoutRef.current }
      liveViewRef.current = view
      updateView(view)
      clearTimeout(timer)
      timer = setTimeout(save, 250)
    }
    const onScroll = () => {
      if (frame === undefined) frame = requestAnimationFrame(capture)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('pagehide', save)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('pagehide', save)
      if (frame !== undefined) cancelAnimationFrame(frame)
      clearTimeout(timer)
    }
  }, [checkpoint, updateView])

  const handleFavoriteToggle = useCallback(
    async (gallery: Gallery) => {
      try {
        await api.library.updateGallery(gallery.source, gallery.source_id, {
          favorited: !gallery.is_favorited,
        })
        toast.success(gallery.is_favorited ? t('library.unfavorited') : t('library.favorited'))
        await refresh()
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [refresh],
  )

  const handleDelete = useCallback(
    async (gallery: Gallery) => {
      if (!window.confirm(t('library.deleteConfirm', { title: gallery.title }))) return
      try {
        await api.library.deleteGallery(gallery.source, gallery.source_id)
        toast.success(t('library.deleted'))
        await refresh()
      } catch {
        toast.error(t('library.updateFailed'))
      }
    },
    [refresh],
  )

  const handleReadingListToggle = useCallback(
    async (g: Gallery) => {
      try {
        await api.library.updateGallery(g.source, g.source_id, {
          in_reading_list: !g.in_reading_list,
        })
        await refresh()
        toast.success(
          g.in_reading_list
            ? t('contextMenu.removeFromReadingList')
            : t('contextMenu.addToReadingList'),
        )
      } catch {
        toast.error(t('common.failedToLoad'))
      }
    },
    [refresh],
  )

  // ── Keyboard grid navigation ────────────────────────────
  const { focusedIndex, registerElement } = useGridKeyboard({
    totalItems: displayGalleries.length,
    colCount,
    onEnter: (i) => {
      const g = displayGalleries[i]
      if (g) openGallery(g)
    },
  })

  const handleRegisterElement = useCallback(
    (index: number, element: HTMLElement | null) => {
      registerElement(index, element)
      const gallery = displayGalleries[index]
      if (!gallery) return
      if (element) itemElementsRef.current.set(gallery.id, element)
      else itemElementsRef.current.delete(gallery.id)
    },
    [displayGalleries, registerElement],
  )

  // First card whose bottom is below the sticky search block. `scrollMargin` can
  // be stale after the filter panel opens (the grid observer is width-only), so
  // the visible start is only a seed: walk backward over cards still under the
  // bar, then forward to the first one that is.
  const visibleAnchor = (): BrowseAnchor | null => {
    const count = displayGalleries.length
    if (count === 0) return null
    const barBottom = Math.max(0, searchBlockRef.current?.getBoundingClientRect().bottom ?? 0)
    const rectAt = (index: number) => {
      const gallery = displayGalleries[index]
      return gallery ? itemElementsRef.current.get(gallery.id)?.getBoundingClientRect() : undefined
    }
    let index = Math.min(visibleStartRef.current, count - 1)
    const seed = rectAt(index)
    if (seed && seed.bottom > barBottom) {
      while (index > 0) {
        const previous = rectAt(index - 1)
        if (!previous || previous.bottom <= barBottom) break
        index -= 1
      }
    } else {
      let found = -1
      for (let i = index + 1; i < count; i += 1) {
        const rect = rectAt(i)
        if (rect && rect.bottom > barBottom) {
          found = i
          break
        }
      }
      if (found < 0) return null
      index = found
    }
    const gallery = displayGalleries[index]
    const rect = rectAt(index)
    if (!gallery || !rect) return null
    return {
      itemId: gallery.id,
      offset: searchStuck ? barBottom + LAYOUT_SWITCH_GAP_PX : rect.top,
      scrollY: window.scrollY,
    }
  }

  const switchLayout = ({
    viewMode: nextViewMode = viewMode,
    densityOverride: nextOverride = densityOverride,
  }: {
    viewMode?: 'grid' | 'list'
    densityOverride?: GridDensityPreference | null
  }) => {
    if (nextViewMode === viewMode && nextOverride === densityOverride) return
    const writePreferences = () => {
      if (nextViewMode !== viewMode) {
        try {
          localStorage.setItem(VIEW_MODE_KEY, nextViewMode)
        } catch {
          // Storage unavailable: the choice just does not persist.
        }
      }
      if (nextOverride !== densityOverride) saveLibraryDensityOverride(nextOverride)
      setViewMode(nextViewMode)
    }
    // A pending session restore owns the view and re-issues for the new layout;
    // saving a view here would overwrite the position being restored.
    if (pendingRestoreRef.current) {
      writePreferences()
      return
    }
    // A second switch reuses the first anchor: measuring now reads a layout
    // that is still mid-transition.
    const anchor = pendingLayoutSwitchRef.current?.anchor ?? visibleAnchor()
    writePreferences()
    if (!anchor) return
    const view = { anchor, layout: { ...layoutRef.current, mode: nextViewMode } }
    liveViewRef.current = view
    updateView(view)
    checkpoint(view)
    if (!searchStuck || typeof anchor.itemId !== 'number') return
    layoutSwitchCounterRef.current += 1
    const next = {
      key: `layout-switch:${layoutSwitchCounterRef.current}`,
      itemId: anchor.itemId,
      anchor,
    }
    pendingLayoutSwitchRef.current = next
    setLayoutSwitch({ key: next.key, itemId: next.itemId })
  }

  const handleGridRestoreApplied = useCallback(
    (request: { key: string; index: number }) => {
      const switching = pendingLayoutSwitchRef.current
      if (switching && switching.key === request.key) {
        const gallery = displayGalleries[request.index]
        const element =
          gallery && gallery.id === switching.itemId
            ? itemElementsRef.current.get(gallery.id)
            : undefined
        // The grid has already marked this token applied and never retries.
        if (!gallery || !element) {
          clearLayoutSwitch()
          return
        }
        const barBottom = Math.max(0, searchBlockRef.current?.getBoundingClientRect().bottom ?? 0)
        window.scrollTo(
          0,
          window.scrollY + element.getBoundingClientRect().top - (barBottom + LAYOUT_SWITCH_GAP_PX),
        )
        clearLayoutSwitch()
        rebaseScrollReveal()
        const view = {
          anchor: captureAnchor(gallery),
          layout: { ...layoutRef.current, mode: viewMode },
        }
        liveViewRef.current = view
        updateView(view)
        checkpoint(view)
        return
      }
      const pending = pendingRestoreRef.current
      if (
        !pending ||
        handledRestoreKeyRef.current === request.key ||
        pending.identityKey !== state.identityKey ||
        pending.key !== request.key ||
        pending.index !== request.index
      )
        return
      const gallery = displayGalleries[request.index]
      const element = gallery ? itemElementsRef.current.get(gallery.id) : null
      if (!element) return
      const rect = element.getBoundingClientRect()
      window.scrollTo(
        0,
        window.scrollY + rect.top - restoreAnchorOffset(pending.offset, rect.height),
      )
      pendingRestoreRef.current = null
      setRestoreRequest(undefined)
      handledRestoreKeyRef.current = pending.key
      acknowledgeRestore(pending.key)
    },
    [
      acknowledgeRestore,
      captureAnchor,
      checkpoint,
      clearLayoutSwitch,
      displayGalleries,
      rebaseScrollReveal,
      state.identityKey,
      updateView,
      viewMode,
    ],
  )

  const toggleSelectedId = useCallback(
    (id: number) => {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        if (next.has(id)) {
          next.delete(id)
        } else {
          next.add(id)
        }
        return next
      })
    },
    [setSelectedIds],
  )

  return (
    <div>
      <PageHeader
        spacing="dense"
        title={t('library.title')}
        meta={total !== null ? `${formatNumber(total)} ${t('library.galleries')}` : undefined}
        actions={
          <>
            <button
              type="button"
              aria-pressed={selectMode}
              onClick={() => {
                setSelectMode(!selectMode)
                setSelectedIds(new Set())
              }}
              className={`px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                selectMode
                  ? 'bg-vault-accent/20 border-vault-accent text-vault-accent'
                  : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-vault-accent'
              }`}
            >
              {t('library.select')}
            </button>
          </>
        }
      />

      <div ref={searchSentinelRef} aria-hidden="true" />
      <div
        ref={searchBlockRef}
        data-testid="library-search-block"
        data-stuck={searchStuck || undefined}
        data-scroll-hidden={searchHidden || undefined}
        // Capture handlers also fire for portalled popups (React bubbles through
        // portals); only focus inside the block counts.
        onFocusCapture={(e) => {
          if (e.currentTarget.contains(e.target as Node)) setSearchFocused(true)
        }}
        onBlurCapture={(e) => {
          if (!e.currentTarget.contains(e.target as Node)) return
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setSearchFocused(false)
        }}
        style={{
          top: 'var(--sat)',
          transform: searchHidden ? 'translateY(calc(-100% - var(--sat)))' : undefined,
        }}
        className={`sticky z-20 -mx-4 px-4 lg:-mx-6 lg:px-6 xl:-mx-8 xl:px-8 py-2 mb-2 bg-vault-bg transition-[transform,box-shadow] duration-200 ${
          searchStuck && !searchHidden ? 'shadow-md shadow-black/30' : ''
        }`}
      >
        {/* Covers the translucent status bar above the stuck block. */}
        {searchStuck && (
          <div
            aria-hidden="true"
            className="absolute inset-x-0 bottom-full h-[var(--sat)] bg-vault-bg"
          />
        )}
        <LibrarySearchBar
          value={inputValue}
          onChange={handleInputChange}
          onCommit={commitSearch}
          onClear={clearSearch}
          onCancel={clearSearch}
          activeFilterCount={filterChips.length}
          filtersOpen={filterPanelOpen}
          onToggleFilters={() => setFilterPanelOpen((v) => !v)}
          favorited={parsed.favorited}
          onToggleFavorited={() => setFilter('favorited', parsed.favorited ? null : 'true')}
          readingList={parsed.readingList}
          onToggleReadingList={() => setFilter('rl', parsed.readingList ? null : 'true')}
          viewControls={
            <LibraryViewControls
              viewMode={viewMode}
              onViewModeChange={(mode) => switchLayout({ viewMode: mode })}
              density={gridDensity}
              densityOverridden={densityOverride !== null}
              onDensityChange={(density) => switchLayout({ densityOverride: density })}
              onFollowSettings={() => switchLayout({ densityOverride: null })}
              onMenuOpenChange={setViewMenuOpen}
            />
          }
        />

        {/* Collapsible filter panel — CSS transition via grid-rows */}
        <div
          id="library-filter-panel"
          inert={!filterPanelOpen}
          className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
            filterPanelOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="overflow-hidden">
            <div className="mt-2 bg-vault-card border border-vault-border rounded-lg p-4">
              <div className="flex flex-wrap gap-4 items-center">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.minRating')}
                  </label>
                  <select
                    value={parsed.rating ?? ''}
                    onChange={(e) => {
                      setFilter('rating', e.target.value ? e.target.value : null)
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    <option value="">{t('library.any')}</option>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <option key={n} value={n}>
                        {n}+
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.source')}
                  </label>
                  <select
                    value={combinedSource}
                    onChange={(e) => {
                      const val = e.target.value
                      if (!val) {
                        setFilter('source', null)
                        setFilter('import', null)
                      } else {
                        const colonIdx = val.indexOf(':')
                        if (colonIdx !== -1) {
                          setFilter('source', val.slice(0, colonIdx))
                          setFilter('import', val.slice(colonIdx + 1))
                        } else {
                          setFilter('source', val)
                          setFilter('import', null)
                        }
                      }
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    <option value="">{t('library.allSources')}</option>
                    {(sourcesData ?? []).map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {sourceDisplayLabel(opt.value, opt.label)}
                      </option>
                    ))}
                  </select>
                </div>
                {categoriesData && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                      {t('library.filterCategory')}
                    </label>
                    <select
                      value={parsed.category ?? ''}
                      onChange={(e) => {
                        setFilter('category', e.target.value || null)
                      }}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                    >
                      <option value="">{t('library.allCategories')}</option>
                      <option value="__uncategorized__">
                        {t('library.categoryUncategorized')}
                      </option>
                      {categoriesData.categories.map((cat) => (
                        <option key={cat} value={cat}>
                          {cat}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {collectionsData && collectionsData.collections.length > 0 && (
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                      {t('collections.filterByCollection')}
                    </label>
                    <select
                      value={parsed.collection ?? ''}
                      onChange={(e) => setFilter('collection', e.target.value || null)}
                      className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                    >
                      <option value="">{t('collections.allCollections')}</option>
                      {collectionsData.collections.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} ({c.gallery_count})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <label className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('library.sort')}
                  </label>
                  <select
                    value={sortValue}
                    onChange={(e) => {
                      setFilter(
                        'sort',
                        e.target.value === 'added_at' ? null : e.target.value || null,
                      )
                    }}
                    className="bg-vault-input border border-vault-border rounded px-2 py-1 text-vault-text text-sm focus:outline-none"
                  >
                    {SORT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label()}
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="button"
                  onClick={() => setSyntaxHelpOpen((v) => !v)}
                  aria-expanded={syntaxHelpOpen}
                  className={`flex items-center gap-1 text-sm transition-colors ${
                    syntaxHelpOpen
                      ? 'text-vault-accent'
                      : 'text-vault-text-muted hover:text-vault-accent'
                  }`}
                >
                  <HelpCircle size={16} />
                  {t('library.syntaxHelp')}
                </button>
              </div>

              {syntaxHelpOpen && (
                <div className="mt-4 p-3 bg-vault-input border border-vault-border rounded-lg text-xs text-vault-text-secondary space-y-1 font-mono">
                  <p>character:rem — {t('library.syntaxTagSearch')}</p>
                  <p>rem — {t('library.syntaxNameOnly')}</p>
                  <p>-general:sketch — {t('library.syntaxExclude')}</p>
                  <p>title:&quot;re zero&quot; — {t('library.syntaxTitle')}</p>
                  <p>source:ehentai — {t('library.syntaxSource')}</p>
                  <p>rating:&gt;=4 — {t('library.syntaxRating')}</p>
                  <p>favorited:true — {t('library.syntaxFavorited')}</p>
                  <p>sort:rating — {t('library.syntaxSort')}</p>
                  <p>collection:5 — {t('library.syntaxCollection')}</p>
                  <p>artist_id:xxx — {t('library.syntaxArtistId')}</p>
                  <p>category:doujinshi — {t('library.syntaxCategory')}</p>
                  <p>import:link — {t('library.syntaxImportMode')}</p>
                  <p>rl:true — {t('library.syntaxReadingList')}</p>
                </div>
              )}
            </div>
          </div>
        </div>

        <LibraryFilterChips
          chips={filterChips}
          onRemove={handleRemoveChip}
          onClearAll={clearFilters}
        />
      </div>

      {isSessionLoading && displayGalleries.length === 0 && <SkeletonGrid />}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-4 text-red-400 flex items-center justify-between gap-3">
          <span>{error.message || t('common.failedToLoad')}</span>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            onClick={() => void retry()}
            className="shrink-0 border border-red-400/40 text-red-400 hover:bg-red-500/10 hover:text-red-400"
          >
            {t('common.retry')}
          </Button>
        </div>
      )}

      {displayGalleries.length > 0 && (
        <VirtualGrid
          items={displayGalleries}
          getItemKey={(gallery) => gallery.id}
          columns={viewMode === 'list' ? { base: 1 } : gridColumns}
          gap={viewMode === 'list' ? 8 : getLibraryGridGap(gridDensity)}
          estimateHeight={viewMode === 'list' ? 150 : estimateLibraryGridRowHeight}
          measureRows={false}
          overscan={viewMode === 'list' ? 8 : 6}
          focusedIndex={focusedIndex}
          onColCountChange={setColCount}
          onRegisterElement={handleRegisterElement}
          onVisibleRangeChange={({ startIndex, visibleStartIndex }) => {
            visibleStartRef.current = visibleStartIndex ?? startIndex
          }}
          onLayoutChange={({ colCount: columns, containerWidth }) => {
            layoutRef.current = { columns, width: containerWidth, mode: viewMode }
          }}
          restoreRequest={
            layoutSwitchRequest ??
            (restoreRequest?.identityKey === state.identityKey ? restoreRequest : undefined)
          }
          onRestoreApplied={handleGridRestoreApplied}
          onLoadMore={state.status === 'error' ? undefined : loadMore}
          hasMore={state.hasMore}
          isLoading={isSessionLoading}
          renderItem={(gallery) => {
            const Card = viewMode === 'list' ? GalleryListCard : LibraryGalleryCard
            // The list card shows plain text, so only the grid card takes the registry colours.
            const cardExtras =
              viewMode === 'list' ? {} : { categories: categoryRegistry?.categories }
            if (selectMode) {
              const isSelected = selectedIds.has(gallery.id)
              return (
                <div
                  onClick={() => {
                    toggleSelectedId(gallery.id)
                  }}
                  onContextMenu={(e) => e.preventDefault()}
                >
                  <Card
                    gallery={gallery}
                    {...cardExtras}
                    thumbUrl={gallery.cover_thumb ?? undefined}
                    selected={isSelected}
                    selectMode={true}
                    onFavoriteToggle={handleFavoriteToggle}
                    onReadingListToggle={handleReadingListToggle}
                    onDelete={handleDelete}
                  />
                </div>
              )
            }
            return (
              <Card
                gallery={gallery}
                {...cardExtras}
                thumbUrl={gallery.cover_thumb ?? undefined}
                onClick={() => openGallery(gallery)}
                onFavoriteToggle={handleFavoriteToggle}
                onReadingListToggle={handleReadingListToggle}
                onDelete={handleDelete}
              />
            )
          }}
        />
      )}

      {!isSessionLoading && displayGalleries.length === 0 && !error && (
        <EmptyState icon={BookOpen} title={t('library.noGalleries')} />
      )}

      {selectMode && selectedIds.size > 0 && (
        <div className="fixed bottom-[calc(4rem+var(--sab))] lg:bottom-0 left-0 right-0 bg-vault-card border-t border-vault-border p-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between z-50">
          <div className="flex items-center gap-3">
            <span className="text-sm text-vault-text font-medium">
              {t('library.selectedCount', { count: String(selectedIds.size) })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedIds(new Set(displayGalleries.map((g) => g.id)))}
              className="h-auto px-1 py-0.5 text-xs text-vault-accent hover:bg-transparent hover:text-vault-accent hover:underline"
            >
              {t('library.selectAll')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedIds(new Set())}
              className="h-auto px-1 py-0.5 text-xs hover:bg-transparent hover:underline"
            >
              {t('library.deselectAll')}
            </Button>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            <Button
              variant="primary"
              size="sm"
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'favorite',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
            >
              {t('library.batchFavorite')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'unfavorite',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
            >
              {t('library.batchUnfavorite')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'add_to_reading_list',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                  setSelectedIds(new Set())
                  setSelectMode(false)
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
            >
              <Bookmark size={14} />
              {t('library.batchAddToReadingList')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={async () => {
                try {
                  const res = await api.library.batchGalleries({
                    action: 'remove_from_reading_list',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                  setSelectedIds(new Set())
                  setSelectMode(false)
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
            >
              <BookmarkCheck size={14} />
              {t('library.batchRemoveFromReadingList')}
            </Button>
            <select
              defaultValue=""
              onChange={async (e) => {
                const rating = Number(e.target.value)
                if (!rating && rating !== 0) return
                try {
                  const res = await api.library.batchGalleries({
                    action: 'rate',
                    gallery_ids: [...selectedIds],
                    rating,
                  })
                  toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
                e.target.value = ''
              }}
              className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
            >
              <option value="" disabled>
                {t('library.batchRate')}
              </option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} ★
                </option>
              ))}
            </select>
            <AddToCollectionMenu
              galleryIds={[...selectedIds]}
              onChanged={async () => {
                await refresh()
                setSelectedIds(new Set())
                setSelectMode(false)
              }}
              className="px-3 py-1.5 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors flex items-center gap-1.5"
            />
            {datasetsData && datasetsData.datasets.length > 0 && (
              <select
                defaultValue=""
                onChange={async (event) => {
                  const datasetId = Number(event.target.value)
                  if (!datasetId) return
                  try {
                    const result = await addDatasetMembers({
                      id: datasetId,
                      selection: { gallery_ids: [...selectedIds] },
                    })
                    toast.success(t('datasets.membersAdded', { count: String(result.added) }))
                    setSelectedIds(new Set())
                    setSelectMode(false)
                  } catch {
                    toast.error(t('datasets.addFailed'))
                  }
                  event.target.value = ''
                }}
                className="px-2 py-1.5 bg-vault-input border border-vault-border rounded text-vault-text text-sm"
              >
                <option value="" disabled>
                  {t('datasets.addToDataset')}
                </option>
                {datasetsData.datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setBatchTagMode('add')
                setBatchTagList([])
                setBatchTagInput('')
              }}
            >
              {t('library.batchAddTags')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setBatchTagMode('remove')
                setBatchTagList([])
                setBatchTagInput('')
              }}
            >
              {t('library.batchRemoveTags')}
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={async () => {
                if (!confirm(t('library.batchDeleteConfirm', { count: String(selectedIds.size) })))
                  return
                try {
                  await api.library.batchGalleries({
                    action: 'delete',
                    gallery_ids: [...selectedIds],
                  })
                  toast.success(t('trash.movedToTrash'))
                  await refresh()
                } catch {
                  toast.error(t('library.updateFailed'))
                }
              }}
            >
              {t('library.batchDelete')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSelectMode(false)
                setSelectedIds(new Set())
              }}
            >
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}

      {batchTagOpened && (
        <Dialog
          open={batchTagMode !== null}
          onOpenChange={(o) => {
            if (!o) setBatchTagMode(null)
          }}
          size="sm"
          initialFocus={batchTagInputRef}
          title={batchTagMode === 'add' ? t('library.batchAddTags') : t('library.batchRemoveTags')}
          footer={
            <>
              <Button onClick={() => setBatchTagMode(null)}>{t('common.cancel')}</Button>
              <Button
                variant="primary"
                disabled={batchTagList.length === 0}
                onClick={async () => {
                  try {
                    const res = await api.library.batchGalleries({
                      action: batchTagMode === 'add' ? 'add_tags' : 'remove_tags',
                      gallery_ids: [...selectedIds],
                      tags: batchTagList,
                    })
                    toast.success(t('library.batchSuccess', { count: String(res.affected) }))
                    setBatchTagMode(null)
                    setBatchTagList([])
                    await refresh()
                  } catch {
                    toast.error(t('library.updateFailed'))
                  }
                }}
              >
                {t('library.batchTagsConfirm')}
              </Button>
            </>
          }
        >
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={batchTagInput}
              onChange={(e) => setBatchTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && batchTagInput.trim()) {
                  setBatchTagList((prev) => [...prev, batchTagInput.trim()])
                  setBatchTagInput('')
                }
              }}
              placeholder={t('library.batchTagsPlaceholder')}
              className="flex-1 bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted text-sm focus:outline-none focus:border-vault-border-hover"
              ref={batchTagInputRef}
            />
          </div>
          <div className="flex flex-wrap gap-1 mb-3 min-h-[2rem]">
            {batchTagList.map((tag, i) => (
              <span
                key={i}
                className="flex items-center gap-1 px-2 py-0.5 bg-vault-accent/10 border border-vault-accent/30 text-vault-accent rounded text-xs"
              >
                {tag}
                <button
                  onClick={() => setBatchTagList((prev) => prev.filter((_, j) => j !== i))}
                  className="hover:text-red-400"
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        </Dialog>
      )}
    </div>
  )
}

export default function LibraryPage() {
  return (
    <PageContainer>
      <Suspense fallback={<SkeletonGrid />}>
        <LibraryContent />
      </Suspense>
    </PageContainer>
  )
}
