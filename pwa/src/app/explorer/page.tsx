'use client'
import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { Folder, LayoutGrid, List, Star, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import type { LibraryDirectory, LibraryFile } from '@/lib/types'
import { SkeletonGrid } from '@/components/Skeleton'

// ── Utilities ─────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

function StarRating({ rating }: { rating: number }) {
  return (
    <span className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          size={12}
          className={s <= rating ? 'text-yellow-400 fill-yellow-400' : 'text-vault-text-secondary'}
        />
      ))}
    </span>
  )
}

// Display names for known sources
const SOURCE_DISPLAY: Record<string, string> = {
  ehentai: 'E-Hentai',
  pixiv: 'Pixiv',
  local: 'Local',
  gallery_dl: 'gallery-dl',
}

function sourceDisplayName(source: string): string {
  return SOURCE_DISPLAY[source] ?? source
}

// ── Main Component ────────────────────────────────────────────────────

const PAGE_LIMIT = 50

// Identifies the currently open gallery by source/source_id pair
interface CurrentGallery {
  source: string
  sourceId: string
  title?: string
}

export default function ExplorerPage() {
  const router = useRouter()

  // Navigation levels:
  //   currentSource=null, currentGallery=null → source folder list (root)
  //   currentSource set, currentGallery=null  → gallery list for that source
  //   currentSource set, currentGallery set   → file list for that gallery
  const [currentSource, setCurrentSource] = useState<string | null>(null)
  const [currentGallery, setCurrentGallery] = useState<CurrentGallery | null>(null)
  const [selectedItems, setSelectedItems] = useState<Set<string | number>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [page, setPage] = useState(0)

  const lastClickRef = useRef<{ id: string | number; time: number } | null>(null)

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Always fetch all directories (we group/filter on the frontend).
  // When at root (source list) we fetch with no source filter.
  // When inside a source, we pass the search query so pagination makes sense.
  const {
    data: dirData,
    mutate: mutateDirs,
    isLoading: dirsLoading,
    error: dirsError,
  } = useSWR(
    currentGallery === null ? ['explorer-dirs', debouncedQuery, page, currentSource] : null,
    () =>
      api.library.listFiles({
        q: debouncedQuery || undefined,
        page,
        limit: PAGE_LIMIT,
      }),
  )

  // Gallery view: list of files inside a gallery
  const {
    data: fileData,
    mutate: mutateFiles,
    isLoading: filesLoading,
    error: filesError,
  } = useSWR(
    currentGallery !== null
      ? ['explorer-files', currentGallery.source, currentGallery.sourceId]
      : null,
    ([, source, sourceId]) => api.library.listGalleryFiles(source, sourceId),
  )

  // ── Click / selection logic ────────────────────────────────────────

  function handleDoubleClickSource(source: string) {
    setCurrentSource(source)
    setSelectedItems(new Set())
    setPage(0)
    setSearchQuery('')
    setDebouncedQuery('')
  }

  function handleDoubleClickGallery(id: string | number) {
    const dir = filteredDirectories.find((d) => d.gallery_id === (id as number))
    if (dir && dir.source) {
      setCurrentGallery({
        source: dir.source,
        sourceId: dir.source_id,
        title: dir.title ?? undefined,
      })
      setSelectedItems(new Set())
    }
  }

  function handleDoubleClickFile(id: string | number) {
    const file = fileData?.files.find((f) => f.filename === id)
    if (file?.page_num != null) {
      router.push(
        `/reader/${currentGallery?.source}/${currentGallery?.sourceId}?page=${file.page_num}`,
      )
    } else {
      router.push(`/reader/${currentGallery?.source}/${currentGallery?.sourceId}`)
    }
  }

  function handleDoubleClick(id: string | number) {
    if (currentGallery !== null) {
      handleDoubleClickFile(id)
    } else if (currentSource !== null) {
      handleDoubleClickGallery(id)
    }
    // Source folders are handled via handleDoubleClickSource (separate handler)
  }

  function handleItemClick(id: string | number, e: React.MouseEvent) {
    const now = Date.now()
    const last = lastClickRef.current
    if (last && last.id === id && now - last.time < 400) {
      handleDoubleClick(id)
      lastClickRef.current = null
      return
    }
    lastClickRef.current = { id, time: now }

    if (e.ctrlKey || e.metaKey) {
      setSelectedItems((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    } else {
      setSelectedItems((prev) => (prev.has(id) && prev.size === 1 ? new Set() : new Set([id])))
    }
  }

  // ── Delete logic ──────────────────────────────────────────────────

  async function handleDelete() {
    if (selectedItems.size === 0) return

    if (currentGallery === null) {
      // Deleting galleries (from source view) — single batch call
      const count = selectedItems.size
      const confirmed = window.confirm(
        t('explorer.deleteGalleriesConfirm', { count: String(count) }),
      )
      if (!confirmed) return

      const galleryIds = Array.from(selectedItems) as number[]
      try {
        const result = await api.library.batchGalleries({
          action: 'delete',
          gallery_ids: galleryIds,
        })
        const skipped = count - result.affected
        if (skipped > 0) {
          toast.success(
            t('explorer.galleriesDeleted', { count: String(result.affected) }) +
              ' ' +
              t('explorer.galleriesDeleteSkipped', { count: String(skipped) }),
          )
        } else {
          toast.success(t('explorer.galleriesDeleted', { count: String(result.affected) }))
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('explorer.deleteFileFailed'))
      }
      setSelectedItems(new Set())
      mutateDirs()
    } else {
      // Deleting individual files
      const confirmed = window.confirm(
        t('explorer.deleteFilesConfirm', { count: String(selectedItems.size) }),
      )
      if (!confirmed) return

      let successCount = 0
      let lastRemainingPages = fileData?.total_files ?? 0

      for (const filename of selectedItems) {
        const file = fileData?.files.find((f) => f.filename === filename)
        if (!file || file.page_num == null) continue
        try {
          const result = await api.library.deleteImage(
            currentGallery?.source ?? '',
            currentGallery?.sourceId ?? '',
            file.page_num,
          )
          successCount++
          lastRemainingPages = result.remaining_pages
        } catch (err) {
          toast.error(err instanceof Error ? err.message : t('explorer.deleteFileFailed'))
        }
      }

      if (successCount > 0) {
        toast.success(t('explorer.filesDeleted', { count: String(successCount) }))
      }

      setSelectedItems(new Set())
      await mutateFiles()

      // If no files remain, prompt to delete the gallery too
      if (lastRemainingPages === 0) {
        const deleteGallery = window.confirm(t('explorer.emptyGalleryPrompt'))
        if (deleteGallery) {
          try {
            await api.library.deleteGallery(currentGallery?.source ?? '', currentGallery?.sourceId ?? '')
            toast.success(t('explorer.galleryDeleted'))
            setCurrentGallery(null)
            mutateDirs()
          } catch (err) {
            toast.error(err instanceof Error ? err.message : t('explorer.deleteFileFailed'))
          }
        }
      }
    }
  }

  // ── Derived state ─────────────────────────────────────────────────

  const allDirectories: LibraryDirectory[] = dirData?.directories ?? []

  // When inside a source, filter directories to that source only.
  // At root level, all directories are used for grouping.
  const filteredDirectories: LibraryDirectory[] =
    currentSource !== null
      ? allDirectories.filter((d) => d.source === currentSource)
      : allDirectories

  const galleryTitle = currentGallery?.title ?? fileData?.title ?? ''
  const files: LibraryFile[] = fileData?.files ?? []
  const totalDirs = currentSource !== null ? filteredDirectories.length : (dirData?.total ?? 0)
  const totalPages = Math.ceil((dirData?.total ?? 0) / PAGE_LIMIT)

  // Group all directories by source for the root view
  const sourceGroups = (() => {
    const groups: Map<
      string,
      { galleries: LibraryDirectory[]; totalFiles: number; totalSize: number }
    > = new Map()
    for (const dir of allDirectories) {
      const src = dir.source ?? 'local'
      if (!groups.has(src)) {
        groups.set(src, { galleries: [], totalFiles: 0, totalSize: 0 })
      }
      const g = groups.get(src)!
      g.galleries.push(dir)
      g.totalFiles += dir.file_count ?? 0
      g.totalSize += dir.disk_size ?? 0
    }
    return groups
  })()

  // ── Breadcrumb segments ────────────────────────────────────────────

  const isRoot = currentSource === null && currentGallery === null
  const isSourceView = currentSource !== null && currentGallery === null
  const isGalleryView = currentGallery !== null

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-screen pb-24">
      {/* Header row */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {/* Back buttons */}
        {isSourceView && (
          <button
            onClick={() => {
              setCurrentSource(null)
              setSelectedItems(new Set())
              setPage(0)
              setSearchQuery('')
              setDebouncedQuery('')
            }}
            className="text-sm text-vault-accent hover:underline shrink-0"
          >
            {t('explorer.backToRoot')}
          </button>
        )}
        {isGalleryView && (
          <button
            onClick={() => {
              setCurrentGallery(null)
              setSelectedItems(new Set())
            }}
            className="text-sm text-vault-accent hover:underline shrink-0"
          >
            {t('explorer.backToSources')}
          </button>
        )}

        <h1 className="text-xl font-bold text-vault-text truncate">
          {isGalleryView
            ? galleryTitle
            : isSourceView
              ? sourceDisplayName(currentSource)
              : t('explorer.title')}
        </h1>

        <div className="flex-1" />

        {/* Search: available at source view level (searching galleries within source) */}
        {isSourceView && (
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value)
              setPage(0)
            }}
            placeholder={t('explorer.searchPlaceholder')}
            className="px-3 py-1.5 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text w-48 md:w-64"
          />
        )}

        <div className="flex gap-1">
          <button
            onClick={() => setViewMode('grid')}
            aria-label={t('explorer.gridView')}
            className={`p-1.5 rounded ${viewMode === 'grid' ? 'bg-vault-accent/20 text-vault-accent' : 'text-vault-text-secondary hover:text-vault-text'}`}
          >
            <LayoutGrid size={18} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            aria-label={t('explorer.listView')}
            className={`p-1.5 rounded ${viewMode === 'list' ? 'bg-vault-accent/20 text-vault-accent' : 'text-vault-text-secondary hover:text-vault-text'}`}
          >
            <List size={18} />
          </button>
        </div>
      </div>

      {/* Breadcrumb */}
      <div className="text-xs text-vault-text-secondary mb-3 flex items-center gap-1 flex-wrap">
        <button
          onClick={() => {
            setCurrentSource(null)
            setCurrentGallery(null)
            setSelectedItems(new Set())
            setPage(0)
            setSearchQuery('')
            setDebouncedQuery('')
          }}
          className={isRoot ? 'text-vault-text font-medium' : 'text-vault-accent hover:underline'}
        >
          {t('explorer.title')}
        </button>
        {(isSourceView || isGalleryView) && (
          <>
            <span>/</span>
            <button
              onClick={() => {
                setCurrentGallery(null)
                setSelectedItems(new Set())
              }}
              className={
                isSourceView
                  ? 'text-vault-text font-medium truncate'
                  : 'text-vault-accent hover:underline truncate'
              }
            >
              {sourceDisplayName(currentSource ?? '')}
            </button>
          </>
        )}
        {isGalleryView && (
          <>
            <span>/</span>
            <span className="text-vault-text font-medium truncate">{galleryTitle}</span>
          </>
        )}
      </div>

      {/* Content */}
      <div
        className="flex-1"
        onClick={(e) => {
          if (e.target === e.currentTarget) setSelectedItems(new Set())
        }}
      >
        {dirsError || filesError ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <AlertTriangle size={32} className="text-red-400" />
            <p className="text-sm text-vault-text-secondary">
              {(dirsError ?? filesError)?.message ?? t('common.errorOccurred')}
            </p>
            <button
              onClick={() => (filesError ? mutateFiles() : mutateDirs())}
              className="px-3 py-1.5 bg-vault-accent text-white rounded-lg text-sm"
            >
              {t('common.retry')}
            </button>
          </div>
        ) : isGalleryView ? (
          <GalleryView
            files={files}
            loading={filesLoading}
            viewMode={viewMode}
            selectedItems={selectedItems}
            onItemClick={handleItemClick}
          />
        ) : isSourceView ? (
          <RootView
            directories={filteredDirectories}
            loading={dirsLoading}
            viewMode={viewMode}
            selectedItems={selectedItems}
            onItemClick={handleItemClick}
          />
        ) : (
          <SourceView
            sourceGroups={sourceGroups}
            loading={dirsLoading}
            viewMode={viewMode}
            onSourceDoubleClick={handleDoubleClickSource}
          />
        )}
      </div>

      {/* Pagination (source view with search, where API paginates) */}
      {isSourceView && (dirData?.total ?? 0) > PAGE_LIMIT && (
        <div className="flex items-center justify-center gap-3 mt-6">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="px-3 py-1.5 bg-vault-input hover:bg-vault-card-hover text-vault-text rounded-lg text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('common.prev')}
          </button>
          <span className="text-sm text-vault-text-secondary">
            {page + 1} / {totalPages}
          </span>
          <button
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1.5 bg-vault-input hover:bg-vault-card-hover text-vault-text rounded-lg text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('common.next')}
          </button>
        </div>
      )}

      {/* Bottom action bar (only in source/gallery view, not at root source list) */}
      {selectedItems.size > 0 && !isRoot && (
        <div className="fixed bottom-[calc(4rem+var(--sab))] lg:bottom-0 left-0 right-0 bg-vault-card border-t border-vault-border p-3 flex items-center justify-between z-50 lg:ml-56">
          <span className="text-sm text-vault-text-secondary">
            {t('explorer.selectedCount', { count: String(selectedItems.size) })}
          </span>
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors"
            >
              {t('explorer.deleteFiles')}
            </button>
            <button
              onClick={() => setSelectedItems(new Set())}
              className="px-3 py-1.5 bg-vault-input hover:bg-vault-card-hover text-vault-text rounded-lg text-sm transition-colors"
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Source View (top-level: grouped by source) ────────────────────────

interface SourceViewProps {
  sourceGroups: Map<
    string,
    { galleries: LibraryDirectory[]; totalFiles: number; totalSize: number }
  >
  loading: boolean
  viewMode: 'grid' | 'list'
  onSourceDoubleClick: (source: string) => void
}

function SourceView({ sourceGroups, loading, viewMode, onSourceDoubleClick }: SourceViewProps) {
  const lastClickRef = useRef<{ id: string; time: number } | null>(null)

  function handleClick(source: string) {
    const now = Date.now()
    const last = lastClickRef.current
    if (last && last.id === source && now - last.time < 400) {
      onSourceDoubleClick(source)
      lastClickRef.current = null
      return
    }
    lastClickRef.current = { id: source, time: now }
  }

  if (loading) {
    return <SkeletonGrid count={4} />
  }

  if (sourceGroups.size === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="text-vault-text-secondary text-sm">{t('explorer.noSources')}</span>
      </div>
    )
  }

  const entries = Array.from(sourceGroups.entries())

  if (viewMode === 'grid') {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {entries.map(([source, info]) => (
          <div
            key={source}
            onClick={() => handleClick(source)}
            onDoubleClick={() => onSourceDoubleClick(source)}
            className="bg-vault-card rounded-lg p-4 cursor-pointer border border-vault-border hover:border-vault-accent/50 hover:bg-vault-card-hover transition-all select-none"
          >
            <div className="flex items-center gap-2 mb-3">
              <Folder size={24} className="text-vault-accent shrink-0" />
              <span className="text-sm font-semibold text-vault-text truncate">
                {sourceDisplayName(source)}
              </span>
            </div>
            <div className="text-xs text-vault-text-secondary space-y-1">
              <div>{t('explorer.galleryCount', { count: String(info.galleries.length) })}</div>
              <div>{t('explorer.totalFiles', { count: String(info.totalFiles) })}</div>
              <div>{formatSize(info.totalSize)}</div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  // List mode
  return (
    <div className="flex flex-col gap-0.5">
      <div className="grid grid-cols-[1fr_100px_80px_100px] gap-2 px-3 py-1.5 text-xs font-medium text-vault-text-secondary border-b border-vault-border">
        <span>{t('explorer.fileName')}</span>
        <span className="text-right">{t('explorer.galleryCount', { count: '' }).trim()}</span>
        <span className="text-right">{t('explorer.totalFiles', { count: '' }).trim()}</span>
        <span className="text-right">{t('explorer.diskSize')}</span>
      </div>
      {entries.map(([source, info]) => (
        <div
          key={source}
          onClick={() => handleClick(source)}
          onDoubleClick={() => onSourceDoubleClick(source)}
          className="grid grid-cols-[1fr_100px_80px_100px] gap-2 px-3 min-h-[48px] items-center rounded-lg cursor-pointer select-none transition-colors hover:bg-vault-card-hover"
        >
          <div className="flex items-center gap-2 min-w-0">
            <Folder size={16} className="text-vault-accent shrink-0" />
            <span className="text-sm text-vault-text truncate">{sourceDisplayName(source)}</span>
          </div>
          <span className="text-xs text-vault-text-secondary text-right">
            {info.galleries.length}
          </span>
          <span className="text-xs text-vault-text-secondary text-right">{info.totalFiles}</span>
          <span className="text-xs text-vault-text-secondary text-right">
            {formatSize(info.totalSize)}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Root View (directory listing within a source) ─────────────────────

interface RootViewProps {
  directories: LibraryDirectory[]
  loading: boolean
  viewMode: 'grid' | 'list'
  selectedItems: Set<string | number>
  onItemClick: (id: string | number, e: React.MouseEvent) => void
}

function RootView({ directories, loading, viewMode, selectedItems, onItemClick }: RootViewProps) {
  if (loading) {
    return <SkeletonGrid count={8} />
  }

  if (directories.length === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="text-vault-text-secondary text-sm">{t('explorer.noGalleries')}</span>
      </div>
    )
  }

  if (viewMode === 'grid') {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {directories.map((dir) => {
          const isSelected = selectedItems.has(dir.gallery_id)
          return (
            <div
              key={dir.gallery_id}
              onClick={(e) => onItemClick(dir.gallery_id, e)}
              className={`bg-vault-card rounded-lg p-3 cursor-pointer border transition-all select-none ${
                isSelected
                  ? 'border-vault-accent ring-2 ring-vault-accent'
                  : 'border-vault-border hover:border-vault-accent/50 hover:bg-vault-card-hover'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <Folder size={20} className="text-vault-accent shrink-0" />
                <span className="text-sm font-medium text-vault-text truncate">{dir.title}</span>
              </div>
              <div className="text-xs text-vault-text-secondary space-y-1">
                <div className="flex items-center justify-between">
                  <span>{t('explorer.files', { count: String(dir.file_count) })}</span>
                  <span>{formatSize(dir.disk_size)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <StarRating rating={dir.my_rating ?? dir.rating} />
                  {dir.source && (
                    <span className="bg-vault-input px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide">
                      {dir.source}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  // List mode
  return (
    <div className="flex flex-col gap-0.5">
      <div className="grid grid-cols-[1fr_80px_80px_80px_80px] gap-2 px-3 py-1.5 text-xs font-medium text-vault-text-secondary border-b border-vault-border">
        <span>{t('explorer.fileName')}</span>
        <span className="text-right">{t('explorer.files', { count: '' }).trim()}</span>
        <span className="text-right">{t('explorer.diskSize')}</span>
        <span>{t('library.metaRating').replace(':', '')}</span>
        <span>{t('library.metaSource')}</span>
      </div>
      {directories.map((dir) => {
        const isSelected = selectedItems.has(dir.gallery_id)
        return (
          <div
            key={dir.gallery_id}
            onClick={(e) => onItemClick(dir.gallery_id, e)}
            className={`grid grid-cols-[1fr_80px_80px_80px_80px] gap-2 px-3 min-h-[48px] items-center rounded-lg cursor-pointer select-none transition-colors ${
              isSelected
                ? 'bg-vault-accent/10 ring-1 ring-vault-accent'
                : 'hover:bg-vault-card-hover'
            }`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <Folder size={16} className="text-vault-accent shrink-0" />
              <span className="text-sm text-vault-text truncate">{dir.title}</span>
            </div>
            <span className="text-xs text-vault-text-secondary text-right">{dir.file_count}</span>
            <span className="text-xs text-vault-text-secondary text-right">
              {formatSize(dir.disk_size)}
            </span>
            <StarRating rating={dir.my_rating ?? dir.rating} />
            <span className="text-xs text-vault-text-secondary truncate">{dir.source ?? '—'}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Gallery View (file listing) ───────────────────────────────────────

interface GalleryViewProps {
  files: LibraryFile[]
  loading: boolean
  viewMode: 'grid' | 'list'
  selectedItems: Set<string | number>
  onItemClick: (id: string | number, e: React.MouseEvent) => void
}

function GalleryView({ files, loading, viewMode, selectedItems, onItemClick }: GalleryViewProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="text-vault-text-secondary text-sm">{t('common.loading')}</span>
      </div>
    )
  }

  if (files.length === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="text-vault-text-secondary text-sm">{t('explorer.emptyDir')}</span>
      </div>
    )
  }

  if (viewMode === 'grid') {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
        {files.map((file) => {
          const id = file.filename
          const isSelected = selectedItems.has(id)
          const thumbSrc = file.thumb_path ?? file.file_path ?? null
          return (
            <div
              key={id}
              onClick={(e) => onItemClick(id, e)}
              className={`relative rounded-lg overflow-hidden cursor-pointer select-none border transition-all ${
                isSelected
                  ? 'border-vault-accent ring-2 ring-vault-accent'
                  : 'border-vault-border hover:border-vault-accent/50'
              }`}
            >
              {/* Thumbnail */}
              <div className="aspect-[3/4] bg-vault-input relative overflow-hidden">
                {thumbSrc ? (
                  <img
                    src={thumbSrc}
                    alt={file.filename}
                    loading="lazy"
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <span className="text-vault-text-secondary text-xs">
                      {t('library.noCover')}
                    </span>
                  </div>
                )}
                {file.is_broken && (
                  <div className="absolute inset-0 bg-red-900/70 flex flex-col items-center justify-center gap-1">
                    <AlertTriangle size={20} className="text-red-300" />
                    <span className="text-xs text-red-200 text-center px-1">
                      {t('explorer.brokenLink')}
                    </span>
                  </div>
                )}
              </div>
              {/* Info below */}
              <div className="p-1.5 bg-vault-card">
                <p className="text-[11px] text-vault-text truncate">{file.filename}</p>
                {file.file_size != null && (
                  <p className="text-[10px] text-vault-text-secondary">
                    {formatSize(file.file_size)}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  // List mode
  return (
    <div className="flex flex-col gap-0.5">
      <div className="grid grid-cols-[40px_1fr_100px_80px_70px] gap-2 px-3 py-1.5 text-xs font-medium text-vault-text-secondary border-b border-vault-border">
        <span />
        <span>{t('explorer.fileName')}</span>
        <span>{t('explorer.dimensions')}</span>
        <span className="text-right">{t('explorer.fileSize')}</span>
        <span>{t('explorer.fileType')}</span>
      </div>
      {files.map((file) => {
        const id = file.filename
        const isSelected = selectedItems.has(id)
        const thumbSrc = file.thumb_path ?? file.file_path ?? null
        return (
          <div
            key={id}
            onClick={(e) => onItemClick(id, e)}
            className={`grid grid-cols-[40px_1fr_100px_80px_70px] gap-2 px-3 min-h-[48px] items-center rounded-lg cursor-pointer select-none transition-colors ${
              isSelected
                ? 'bg-vault-accent/10 ring-1 ring-vault-accent'
                : 'hover:bg-vault-card-hover'
            }`}
          >
            {/* Small thumbnail */}
            <div className="w-10 h-10 rounded overflow-hidden bg-vault-input shrink-0 relative">
              {thumbSrc ? (
                <img src={thumbSrc} alt="" loading="lazy" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <span className="text-[8px] text-vault-text-secondary">—</span>
                </div>
              )}
              {file.is_broken && (
                <div className="absolute inset-0 bg-red-900/60 flex items-center justify-center">
                  <AlertTriangle size={12} className="text-red-300" />
                </div>
              )}
            </div>
            <span
              className={`text-sm truncate ${file.is_broken ? 'text-red-400' : 'text-vault-text'}`}
            >
              {file.filename}
            </span>
            <span className="text-xs text-vault-text-secondary">
              {file.width != null && file.height != null ? `${file.width}×${file.height}` : '—'}
            </span>
            <span className="text-xs text-vault-text-secondary text-right">
              {file.file_size != null ? formatSize(file.file_size) : '—'}
            </span>
            <span className="text-xs text-vault-text-secondary truncate">{file.media_type}</span>
          </div>
        )
      })}
    </div>
  )
}
