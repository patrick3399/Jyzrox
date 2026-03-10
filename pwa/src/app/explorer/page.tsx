'use client'
import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { Folder, LayoutGrid, List, Star, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import type { LibraryDirectory, LibraryFile } from '@/lib/types'

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

// ── Main Component ────────────────────────────────────────────────────

const PAGE_LIMIT = 50

export default function ExplorerPage() {
  const router = useRouter()

  const [currentGalleryId, setCurrentGalleryId] = useState<number | null>(null)
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

  // Root view: list of gallery directories
  const {
    data: dirData,
    mutate: mutateDirs,
    isLoading: dirsLoading,
  } = useSWR(
    currentGalleryId === null ? ['explorer-dirs', debouncedQuery, page] : null,
    () => api.library.listFiles({ q: debouncedQuery || undefined, page, limit: PAGE_LIMIT }),
  )

  // Gallery view: list of files inside a gallery
  const {
    data: fileData,
    mutate: mutateFiles,
    isLoading: filesLoading,
  } = useSWR(
    currentGalleryId !== null ? ['explorer-files', currentGalleryId] : null,
    () => api.library.listGalleryFiles(currentGalleryId!),
  )

  // ── Click / selection logic ────────────────────────────────────────

  function handleDoubleClick(id: string | number) {
    if (currentGalleryId === null) {
      // Navigate into gallery
      setCurrentGalleryId(id as number)
      setSelectedItems(new Set())
    } else {
      // Find the file by filename and navigate to reader at that page
      const file = fileData?.files.find((f) => f.filename === id)
      if (file?.page_num != null) {
        router.push(`/reader/${currentGalleryId}?page=${file.page_num}`)
      } else {
        router.push(`/reader/${currentGalleryId}`)
      }
    }
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
      setSelectedItems((prev) =>
        prev.has(id) && prev.size === 1 ? new Set() : new Set([id]),
      )
    }
  }

  // ── Delete logic ──────────────────────────────────────────────────

  async function handleDelete() {
    if (selectedItems.size === 0) return

    if (currentGalleryId === null) {
      // Deleting galleries
      for (const id of selectedItems) {
        const dir = dirData?.directories.find((d) => d.gallery_id === (id as number))
        const title = dir?.title ?? String(id)
        const confirmed = window.confirm(
          t('explorer.deleteGalleryConfirm', { title }),
        )
        if (!confirmed) continue
        try {
          await api.library.deleteGallery(id as number)
          toast.success(t('explorer.galleryDeleted'))
        } catch (err) {
          toast.error(err instanceof Error ? err.message : t('explorer.deleteFileFailed'))
        }
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
          const result = await api.library.deleteImage(currentGalleryId, file.page_num)
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
            await api.library.deleteGallery(currentGalleryId)
            toast.success(t('explorer.galleryDeleted'))
            setCurrentGalleryId(null)
            mutateDirs()
          } catch (err) {
            toast.error(err instanceof Error ? err.message : t('explorer.deleteFileFailed'))
          }
        }
      }
    }
  }

  // ── Derived state ─────────────────────────────────────────────────

  const galleryTitle = fileData?.title ?? ''
  const directories: LibraryDirectory[] = dirData?.directories ?? []
  const files: LibraryFile[] = fileData?.files ?? []
  const totalDirs = dirData?.total ?? 0
  const totalPages = Math.ceil(totalDirs / PAGE_LIMIT)

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-screen pb-24">
      {/* Header row */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {currentGalleryId !== null && (
          <button
            onClick={() => {
              setCurrentGalleryId(null)
              setSelectedItems(new Set())
            }}
            className="text-sm text-vault-accent hover:underline shrink-0"
          >
            {t('explorer.backToRoot')}
          </button>
        )}

        <h1 className="text-xl font-bold text-vault-text truncate">
          {currentGalleryId !== null ? galleryTitle : t('explorer.title')}
        </h1>

        <div className="flex-1" />

        {currentGalleryId === null && (
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

      {/* Breadcrumb for gallery view */}
      {currentGalleryId !== null && (
        <div className="text-xs text-vault-text-secondary mb-3 flex items-center gap-1">
          <button
            onClick={() => {
              setCurrentGalleryId(null)
              setSelectedItems(new Set())
            }}
            className="text-vault-accent hover:underline"
          >
            {t('explorer.title')}
          </button>
          <span>/</span>
          <span className="truncate">{galleryTitle}</span>
        </div>
      )}

      {/* Content */}
      <div
        className="flex-1"
        onClick={(e) => {
          if (e.target === e.currentTarget) setSelectedItems(new Set())
        }}
      >
        {currentGalleryId === null ? (
          <RootView
            directories={directories}
            loading={dirsLoading}
            viewMode={viewMode}
            selectedItems={selectedItems}
            onItemClick={handleItemClick}
          />
        ) : (
          <GalleryView
            files={files}
            loading={filesLoading}
            viewMode={viewMode}
            selectedItems={selectedItems}
            onItemClick={handleItemClick}
          />
        )}
      </div>

      {/* Pagination (root view only) */}
      {currentGalleryId === null && totalDirs > PAGE_LIMIT && (
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

      {/* Bottom action bar */}
      {selectedItems.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-vault-card border-t border-vault-border p-3 flex items-center justify-between z-50 lg:ml-56">
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

// ── Root View (directory listing) ────────────────────────────────────

interface RootViewProps {
  directories: LibraryDirectory[]
  loading: boolean
  viewMode: 'grid' | 'list'
  selectedItems: Set<string | number>
  onItemClick: (id: string | number, e: React.MouseEvent) => void
}

function RootView({ directories, loading, viewMode, selectedItems, onItemClick }: RootViewProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="text-vault-text-secondary text-sm">{t('common.loading')}</span>
      </div>
    )
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
                  <StarRating rating={dir.rating} />
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
            <span className="text-xs text-vault-text-secondary text-right">{formatSize(dir.disk_size)}</span>
            <StarRating rating={dir.rating} />
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
                    <span className="text-vault-text-secondary text-xs">{t('library.noCover')}</span>
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
                  <p className="text-[10px] text-vault-text-secondary">{formatSize(file.file_size)}</p>
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
                <img
                  src={thumbSrc}
                  alt=""
                  loading="lazy"
                  className="w-full h-full object-cover"
                />
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
              {file.width != null && file.height != null
                ? `${file.width}×${file.height}`
                : '—'}
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
