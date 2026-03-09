'use client'

import { useState, useEffect } from 'react'
import {
  Folder,
  ChevronRight,
  FolderInput,
  ArrowLeft,
  Search,
  HardDrive,
  X,
  Plus,
  RefreshCw,
  CircleDot,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  useBrowseFs,
  useMountPoints,
  useImportProgress,
  useStartImport,
  useLibraries,
  useMonitorStatus,
  useAutoDiscover,
  useAddLibrary,
  useRemoveLibrary,
  useToggleMonitor,
  useRescanLibraryPath,
} from '@/hooks/useImport'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'

// ── Progress bar for active import ───────────────────────────────────

function ActiveImportRow({ galleryId, onDone }: { galleryId: number; onDone: () => void }) {
  const { data } = useImportProgress(galleryId)

  const isTerminal =
    data?.status === 'done' ||
    data?.status === 'imported' ||
    data?.status === 'unknown'

  useEffect(() => {
    if (!isTerminal) return
    const timer = setTimeout(onDone, 5000)
    return () => clearTimeout(timer)
  }, [isTerminal, onDone])

  if (!data) return null

  const pct =
    data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0
  const isUnknown = data.status === 'unknown'

  return (
    <div className="bg-vault-input border border-vault-border rounded-lg px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-vault-text">
          {t('import.progress', { processed: data.processed, total: data.total })}
        </span>
        <span
          className={`text-xs font-medium ${isTerminal ? 'text-green-400' : 'text-blue-400'}`}
        >
          {isTerminal ? '100%' : `${pct}%`}
        </span>
      </div>
      <div className="h-1.5 bg-vault-border rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${isTerminal ? 'bg-green-500' : 'bg-blue-500'}`}
          style={{ width: `${isTerminal ? 100 : pct}%` }}
        />
      </div>
      {isUnknown && (
        <p className="text-xs text-vault-text-muted mt-1">{t('import.done')}</p>
      )}
    </div>
  )
}

// ── Folder Picker modal ───────────────────────────────────────────────

function FolderPicker({
  onSelect,
  onClose,
}: {
  onSelect: (path: string) => void
  onClose: () => void
}) {
  const [currentPath, setCurrentPath] = useState<string | null>(null)
  const [editingPath, setEditingPath] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const { data: mountData, isLoading: mountsLoading } = useMountPoints()
  const { data: fsData, isLoading: fsLoading } = useBrowseFs(currentPath ?? '', {
    enabled: currentPath !== null,
  })

  // When currentPath is null, show mount points; otherwise show filesystem
  const showMounts = currentPath === null

  const navigate = (path: string) => {
    setCurrentPath(path)
    setEditingPath(path)
  }

  const navigateInto = (name: string) => {
    if (currentPath === null) return
    const next = `${currentPath === '/' ? '' : currentPath}/${name}`
    setCurrentPath(next)
    setEditingPath(next)
  }

  const goUp = () => {
    if (currentPath === null) return
    if (fsData?.parent != null) {
      setCurrentPath(fsData.parent)
      setEditingPath(fsData.parent)
    } else {
      // At filesystem root — go back to mount points view
      setCurrentPath(null)
      setEditingPath('')
    }
  }

  const handlePathSubmit = () => {
    const trimmed = editingPath.trim()
    if (trimmed && trimmed.startsWith('/')) {
      setCurrentPath(trimmed)
      setIsEditing(false)
    }
  }

  const isLoading = showMounts ? mountsLoading : fsLoading
  const displayPath = currentPath ?? t('import.folderPicker.mountPoints')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-vault-card border border-vault-border rounded-xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-vault-border">
          {!showMounts && (
            <button
              onClick={goUp}
              className="text-vault-text-muted hover:text-vault-text transition-colors shrink-0"
            >
              <ArrowLeft size={16} />
            </button>
          )}
          <h3 className="text-sm font-medium text-vault-text">
            {t('import.folderPicker.title')}
          </h3>
          <button
            onClick={onClose}
            className="ml-auto text-vault-text-muted hover:text-vault-text transition-colors shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        {/* Editable path input */}
        <div className="px-4 py-2 border-b border-vault-border bg-vault-bg">
          <div className="flex items-center gap-2">
            <p className="text-xs text-vault-text-muted shrink-0">{t('import.folderPicker.path')}</p>
            {isEditing ? (
              <input
                type="text"
                value={editingPath}
                onChange={(e) => setEditingPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handlePathSubmit()
                  if (e.key === 'Escape') { setEditingPath(currentPath ?? ''); setIsEditing(false) }
                }}
                onBlur={handlePathSubmit}
                autoFocus
                className="flex-1 bg-vault-input border border-vault-accent rounded px-2 py-1 text-xs font-mono text-vault-text focus:outline-none"
              />
            ) : (
              <button
                onClick={() => { setEditingPath(currentPath ?? '/'); setIsEditing(true) }}
                className="flex-1 text-left text-xs font-mono text-vault-accent hover:text-vault-text truncate transition-colors"
              >
                {displayPath}
              </button>
            )}
          </div>
        </div>

        {/* Directory listing */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <LoadingSpinner />
            </div>
          ) : showMounts ? (
            <>
              {/* Mount points list */}
              {!mountData?.mounts || mountData.mounts.length === 0 ? (
                <p className="text-center py-8 text-sm text-vault-text-muted">
                  {t('import.folderPicker.noMounts')}
                </p>
              ) : (
                mountData.mounts.map((mount) => (
                  <button
                    key={mount.path}
                    onClick={() => navigate(mount.path)}
                    className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-vault-card-hover transition-colors text-left border-b border-vault-border/30"
                  >
                    <HardDrive size={15} className="text-vault-accent shrink-0" />
                    <span className="text-sm text-vault-text truncate flex-1 font-mono">
                      {mount.path}
                    </span>
                    <ChevronRight size={14} className="text-vault-text-muted shrink-0" />
                  </button>
                ))
              )}
              {/* Browse root filesystem option */}
              <button
                onClick={() => navigate('/')}
                className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-vault-card-hover transition-colors text-left border-t border-vault-border/50"
              >
                <Folder size={15} className="text-vault-text-muted shrink-0" />
                <span className="text-sm text-vault-text-muted truncate flex-1 font-mono">/</span>
                <span className="text-xs text-vault-text-muted shrink-0">
                  {t('import.folderPicker.browseRoot')}
                </span>
                <ChevronRight size={14} className="text-vault-text-muted shrink-0" />
              </button>
            </>
          ) : fsData?.entries.length === 0 ? (
            <p className="text-center py-8 text-sm text-vault-text-muted">
              {t('import.dir.empty')}
            </p>
          ) : (
            fsData?.entries.map((entry) => (
              <button
                key={entry.name}
                onClick={() => navigateInto(entry.name)}
                className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-vault-card-hover transition-colors text-left border-b border-vault-border/30"
              >
                <Folder size={15} className="text-yellow-400/80 shrink-0" />
                <span className="text-sm text-vault-text truncate flex-1 font-mono">
                  {currentPath === '/' ? `/${entry.name}` : `${currentPath}/${entry.name}`}
                </span>
                <ChevronRight size={14} className="text-vault-text-muted shrink-0" />
              </button>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-vault-border">
          <button
            onClick={() => onSelect(currentPath ?? '/')}
            disabled={showMounts}
            className="w-full px-3 py-2.5 text-sm bg-vault-accent text-white rounded font-medium hover:bg-vault-accent/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('import.folderPicker.select')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Zone A: Monitored Folders ─────────────────────────────────────────

function ZoneA() {
  const { data: libraries, mutate: mutateLibraries } = useLibraries()
  const { data: monitorData, mutate: mutateMonitor } = useMonitorStatus()
  const { trigger: addLib } = useAddLibrary()
  const { trigger: removeLib } = useRemoveLibrary()
  const { trigger: toggleMonitor, isMutating: togglingMonitor } = useToggleMonitor()
  const { trigger: rescanPath } = useRescanLibraryPath()
  const { trigger: discover, isMutating: discovering } = useAutoDiscover()
  const [rescanningId, setRescanningId] = useState<number | null>(null)
  const [showFolderPicker, setShowFolderPicker] = useState(false)

  const handleMonitorToggle = async () => {
    if (!monitorData) return
    try {
      await toggleMonitor(!monitorData.running)
      mutateMonitor()
    } catch {
      toast.error(t('common.failedToLoad'))
    }
  }

  const handleRescanPath = async (libraryId: number) => {
    setRescanningId(libraryId)
    try {
      await rescanPath(libraryId)
      toast.success(t('import.zoneA.rescan'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    } finally {
      setRescanningId(null)
    }
  }

  const handleDiscover = async () => {
    try {
      await discover()
      toast.success(t('import.discover.started'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
      {/* Zone header */}
      <div className="px-5 py-4 border-b border-vault-border">
        <div className="flex items-center gap-2 mb-1">
          <HardDrive size={15} className="text-vault-accent shrink-0" />
          <h2 className="text-sm font-semibold text-vault-text">{t('import.zoneA.title')}</h2>
        </div>
        <p className="text-xs text-vault-text-muted">{t('import.zoneA.desc')}</p>
      </div>

      <div className="px-5 py-4 space-y-3">
        {/* Library paths list */}
        {libraries && libraries.length > 0 ? (
          <div className="space-y-2">
            {libraries.map((lib) => (
              <div
                key={lib.path}
                className="flex items-center gap-2 px-3 py-2.5 bg-vault-input border border-vault-border rounded-lg"
              >
                <HardDrive size={14} className="text-vault-text-muted shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-mono text-vault-text truncate">{lib.path}</p>
                  {lib.label && (
                    <p className="text-[11px] text-vault-text-muted mt-0.5">{lib.label}</p>
                  )}
                </div>
                {/* Online/offline status */}
                <span
                  className={`flex items-center gap-1 text-[11px] shrink-0 ${lib.exists ? 'text-green-400' : 'text-red-400'}`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${lib.exists ? 'bg-green-400' : 'bg-red-400'}`}
                  />
                  {lib.exists ? t('import.zoneA.online') : t('import.zoneA.offline')}
                </span>
                {/* Rescan button */}
                {lib.id !== null && (
                  <button
                    onClick={() => handleRescanPath(lib.id!)}
                    disabled={rescanningId === lib.id}
                    title={t('import.zoneA.rescan')}
                    className="shrink-0 p-1.5 text-vault-text-muted hover:text-vault-accent transition-colors disabled:opacity-40"
                  >
                    <RefreshCw size={13} className={rescanningId === lib.id ? 'animate-spin' : ''} />
                  </button>
                )}
                {/* Remove button */}
                {lib.id !== null && (
                  <button
                    onClick={async () => {
                      await removeLib(lib.id!)
                      mutateLibraries()
                    }}
                    className="shrink-0 text-red-400/60 hover:text-red-400 transition-colors"
                    title="Remove"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-vault-text-muted py-2">{t('import.noLibraries')}</p>
        )}

        {/* Add new path */}
        <div className="space-y-2">
          {/* Folder picker trigger */}
          <button
            onClick={() => setShowFolderPicker(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-vault-accent text-white rounded text-sm hover:bg-vault-accent/90 transition-colors"
          >
            <Plus size={14} />
            {t('import.zoneA.addLibrary')}
          </button>
        </div>

        {/* Folder picker modal */}
        {showFolderPicker && (
          <FolderPicker
            onSelect={async (path) => {
              try {
                await addLib({ path })
                mutateLibraries()
                toast.success(t('settings.media.pathAdded'))
                setShowFolderPicker(false)
              } catch {
                toast.error(t('settings.media.pathFailed'))
              }
            }}
            onClose={() => setShowFolderPicker(false)}
          />
        )}

        {/* File Monitor toggle + Auto-discover */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-3">
            <span className="text-sm text-vault-text">
              {monitorData?.running
                ? t('settings.media.monitor.active')
                : t('settings.media.monitor.inactive')}
            </span>
            <button
              onClick={handleMonitorToggle}
              disabled={togglingMonitor || !monitorData}
              className={`relative w-10 h-5 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                monitorData?.running ? 'bg-vault-accent' : 'bg-vault-border'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${
                  monitorData?.running ? 'translate-x-5' : ''
                }`}
              />
            </button>
          </div>
          <button
            onClick={handleDiscover}
            disabled={discovering}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-vault-input border border-vault-border hover:border-vault-accent/50 text-vault-text-secondary hover:text-vault-text rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          >
            <Search size={12} />
            {discovering ? t('import.discover.running') : t('import.discover')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Zone B: Import into System ────────────────────────────────────────

function ZoneB() {
  const [selectedDir, setSelectedDir] = useState<string | null>(null)
  const [titleInput, setTitleInput] = useState('')
  const [activeImports, setActiveImports] = useState<number[]>([])
  const [showImportPicker, setShowImportPicker] = useState(false)

  const { trigger: startImport, isMutating: importing } = useStartImport()

  const handleStartImport = async () => {
    if (!selectedDir) return
    try {
      const result = await startImport({
        sourceDir: selectedDir,
        title: titleInput.trim() || undefined,
      })
      toast.success(t('import.importing'))
      setActiveImports((prev) => [...prev, result.gallery_id])
      setSelectedDir(null)
      setTitleInput('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const inputClass =
    'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
      {/* Zone header */}
      <div className="px-5 py-4 border-b border-vault-border">
        <div className="flex items-center gap-2 mb-1">
          <FolderInput size={15} className="text-vault-accent shrink-0" />
          <h2 className="text-sm font-semibold text-vault-text">{t('import.zoneB.title')}</h2>
        </div>
        <p className="text-xs text-vault-text-muted">{t('import.zoneB.desc')}</p>
      </div>

      <div className="p-4 space-y-3">
        {/* Active Imports */}
        {activeImports.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-vault-text-secondary uppercase tracking-wide mb-2">
              {t('import.active')}
            </h3>
            <div className="space-y-2">
              {activeImports.map((id) => (
                <ActiveImportRow
                  key={id}
                  galleryId={id}
                  onDone={() => setActiveImports((prev) => prev.filter((i) => i !== id))}
                />
              ))}
            </div>
          </div>
        )}

        {/* Folder picker trigger */}
        <button
          onClick={() => setShowImportPicker(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-vault-accent text-white rounded text-sm hover:bg-vault-accent/90 transition-colors"
        >
          <Plus size={14} />
          {t('import.zoneB.selectFolder')}
        </button>

        {/* FolderPicker modal */}
        {showImportPicker && (
          <FolderPicker
            onSelect={(path) => {
              setSelectedDir(path)
              setTitleInput(path.split('/').pop() ?? 'Imported')
              setShowImportPicker(false)
            }}
            onClose={() => setShowImportPicker(false)}
          />
        )}

        {/* Import options panel — shown when a dir is selected */}
        {selectedDir && (
          <div className="bg-vault-card border border-vault-accent/30 rounded-xl p-5 space-y-4">
            <div>
              <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">
                {t('import.browse')}
              </p>
              <div className="flex items-center gap-2">
                <p className="text-sm text-vault-text font-mono truncate flex-1">{selectedDir}</p>
                <button
                  onClick={() => setShowImportPicker(true)}
                  className="shrink-0 text-xs text-vault-text-muted hover:text-vault-accent transition-colors"
                >
                  {t('import.zoneB.change')}
                </button>
              </div>
            </div>

            {/* Title */}
            <div>
              <label className="block text-xs text-vault-text-muted mb-1">
                {t('import.gallery.title')}
              </label>
              <input
                type="text"
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
                placeholder={selectedDir.split('/').pop() ?? ''}
                className={inputClass}
              />
            </div>

            <button
              onClick={handleStartImport}
              disabled={importing}
              className="w-full px-4 py-2.5 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors"
            >
              {importing ? t('import.importing') : t('import.start')}
            </button>
          </div>
        )}

      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────

export default function ImportPage() {
  const { data: monitorData } = useMonitorStatus()

  return (
    <div className="min-h-screen bg-vault-bg text-vault-text">
      <div className="max-w-3xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <FolderInput size={22} className="text-vault-accent shrink-0" />
          <h1 className="text-2xl font-bold text-vault-text">{t('import.title')}</h1>
          {monitorData && (
            <span
              className="ml-auto flex items-center gap-1 text-xs text-vault-text-muted"
              title={monitorData.running ? t('import.monitor.active') : t('import.monitor.inactive')}
            >
              <CircleDot
                size={12}
                className={monitorData.running ? 'text-green-400' : 'text-vault-text-muted'}
              />
              {monitorData.running ? t('import.monitor.active') : t('import.monitor.inactive')}
            </span>
          )}
        </div>

        {/* A Zone: Monitored Folders */}
        <ZoneA />

        {/* B Zone: Import into System */}
        <ZoneB />
      </div>
    </div>
  )
}
