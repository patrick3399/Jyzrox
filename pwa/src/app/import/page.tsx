'use client'

import { useState, useEffect } from 'react'
import {
  Folder,
  ChevronRight,
  FolderInput,
  ArrowLeft,
  HardDrive,
  X,
  Plus,
  RefreshCw,
  CircleDot,
  Check,
  ChevronDown,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  useBrowseFs,
  useMountPoints,
  useBatchScan,
  useBatchStart,
  useBatchProgress,
  useLibraries,
  useMonitorStatus,
  useAddLibrary,
  useRemoveLibrary,
  useToggleMonitor,
  useRescanLibraryPath,
} from '@/hooks/useImport'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'

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

        {/* File Monitor toggle */}
        <div className="flex items-center gap-3 pt-1">
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
      </div>
    </div>
  )
}

// ── Zone B: Batch Import ──────────────────────────────────────────────

type BatchMatch = {
  rel_path: string
  abs_path: string
  artist: string | null
  title: string
  file_count: number
  selected: boolean
}

function ZoneB() {
  const [phase, setPhase] = useState<'idle' | 'scanning' | 'previewing' | 'importing' | 'done'>('idle')
  const [selectedDir, setSelectedDir] = useState<string | null>(null)
  const [pattern, setPattern] = useState('{title}')
  const [mode, setMode] = useState<'copy' | 'link'>('copy')
  const [showPicker, setShowPicker] = useState(false)
  const [matches, setMatches] = useState<BatchMatch[]>([])
  const [unmatched, setUnmatched] = useState<Array<{ rel_path: string; file_count: number }>>([])
  const [batchId, setBatchId] = useState<string | null>(null)
  const [unmatchedOpen, setUnmatchedOpen] = useState(false)

  const { trigger: scan, isMutating: scanLoading } = useBatchScan()
  const { trigger: startBatch } = useBatchStart()
  const { data: progress } = useBatchProgress(batchId)

  const presets = ['{title}', '{artist}/{title}', '{_}/{artist}/{title}']

  const updateMatch = (idx: number, field: string, value: string | boolean | null) => {
    setMatches((prev) => prev.map((m, i) => (i === idx ? { ...m, [field]: value } : m)))
  }

  const handleScan = async () => {
    if (!selectedDir) return
    try {
      const result = await scan({ rootDir: selectedDir, pattern })
      setMatches(result.matches.map((m) => ({ ...m, selected: true })))
      setUnmatched(result.unmatched)
      setPhase('previewing')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const handleImport = async () => {
    const selected = matches.filter((m) => m.selected)
    if (selected.length === 0) return
    try {
      const result = await startBatch({
        rootDir: selectedDir!,
        mode,
        galleries: selected.map((m) => ({ path: m.abs_path, artist: m.artist, title: m.title })),
      })
      setBatchId(result.batch_id)
      setPhase('importing')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const handleReset = () => {
    setPhase('idle')
    setSelectedDir(null)
    setPattern('{title}')
    setMode('copy')
    setMatches([])
    setUnmatched([])
    setBatchId(null)
    setUnmatchedOpen(false)
  }

  useEffect(() => {
    if (progress?.status === 'done') {
      setPhase('done')
    }
  }, [progress?.status])

  const selectedCount = matches.filter((m) => m.selected).length
  const allSelected = matches.length > 0 && selectedCount === matches.length

  const editInputClass =
    'bg-transparent border-b border-vault-border focus:border-vault-accent focus:outline-none text-sm text-vault-text w-full'

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

      <div className="p-4 space-y-4">

        {/* ── idle: select folder ── */}
        {phase === 'idle' && (
          <>
            <button
              onClick={() => setShowPicker(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-vault-accent text-white rounded text-sm hover:bg-vault-accent/90 transition-colors"
            >
              <Plus size={14} />
              {t('import.zoneB.selectFolder')}
            </button>
            {showPicker && (
              <FolderPicker
                onSelect={(path) => {
                  setSelectedDir(path)
                  setShowPicker(false)
                  setPhase('scanning')
                }}
                onClose={() => setShowPicker(false)}
              />
            )}
          </>
        )}

        {/* ── scanning: show path + pattern + mode + scan button ── */}
        {phase === 'scanning' && (
          <div className="space-y-4">
            {/* Selected path */}
            <div className="flex items-center gap-2">
              <p className="text-sm font-mono text-vault-text truncate flex-1">{selectedDir}</p>
              <button
                onClick={() => setShowPicker(true)}
                className="shrink-0 text-xs text-vault-text-muted hover:text-vault-accent transition-colors"
              >
                {t('import.zoneB.change')}
              </button>
            </div>

            {/* Pattern input */}
            <div>
              <label className="block text-xs text-vault-text-muted mb-1">
                {t('import.batch.pattern')}
              </label>
              <input
                type="text"
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                placeholder="{title}"
                className="w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm font-mono"
              />
              <p className="text-[11px] text-vault-text-muted mt-1">{t('import.batch.patternHelp')}</p>
            </div>

            {/* Preset chips */}
            <div>
              <p className="text-xs text-vault-text-muted mb-1.5">{t('import.batch.presets')}</p>
              <div className="flex flex-wrap gap-1.5">
                {presets.map((p) => (
                  <button
                    key={p}
                    onClick={() => setPattern(p)}
                    className={`px-2 py-1 rounded text-xs font-mono transition-colors ${
                      pattern === p
                        ? 'bg-vault-accent text-white'
                        : 'bg-vault-input text-vault-text-muted hover:text-vault-text'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {/* Mode toggle */}
            <div>
              <div className="flex rounded overflow-hidden border border-vault-border w-fit">
                <button
                  onClick={() => setMode('copy')}
                  className={`px-4 py-1.5 text-xs font-medium transition-colors ${
                    mode === 'copy' ? 'bg-vault-accent text-white' : 'bg-vault-input text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('import.batch.modeCopy')}
                </button>
                <button
                  onClick={() => setMode('link')}
                  className={`px-4 py-1.5 text-xs font-medium transition-colors ${
                    mode === 'link' ? 'bg-vault-accent text-white' : 'bg-vault-input text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('import.batch.modeLink')}
                </button>
              </div>
              <p className="text-[11px] text-vault-text-muted mt-1">
                {mode === 'copy' ? t('import.batch.modeCopyDesc') : t('import.batch.modeLinkDesc')}
              </p>
            </div>

            {/* Scan button */}
            <button
              onClick={handleScan}
              disabled={scanLoading || !pattern.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-sm font-medium transition-colors"
            >
              {scanLoading ? (
                <>
                  <LoadingSpinner />
                  {t('import.batch.scanning')}
                </>
              ) : (
                t('import.batch.scan')
              )}
            </button>

            {showPicker && (
              <FolderPicker
                onSelect={(path) => {
                  setSelectedDir(path)
                  setShowPicker(false)
                }}
                onClose={() => setShowPicker(false)}
              />
            )}
          </div>
        )}

        {/* ── previewing: table of matches ── */}
        {phase === 'previewing' && (
          <div className="space-y-4">
            {/* Summary */}
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-vault-text">
                {t('import.batch.matchCount', { count: String(matches.length) })}
              </span>
              {unmatched.length > 0 && (
                <span className="text-sm text-vault-text-muted">
                  {t('import.batch.unmatchedCount', { count: String(unmatched.length) })}
                </span>
              )}
              <button
                onClick={() => { setPhase('scanning'); }}
                className="ml-auto text-xs text-vault-text-muted hover:text-vault-accent transition-colors"
              >
                {t('import.zoneB.change')}
              </button>
            </div>

            {matches.length === 0 ? (
              <p className="text-sm text-vault-text-muted py-4 text-center">
                {t('import.batch.noMatches')}
              </p>
            ) : (
              <div className="border border-vault-border rounded-lg overflow-hidden">
                {/* Table header */}
                <div className="grid grid-cols-[auto_1fr_1fr_auto] gap-2 px-3 py-2 bg-vault-input border-b border-vault-border text-xs text-vault-text-muted font-medium">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={(e) =>
                      setMatches((prev) => prev.map((m) => ({ ...m, selected: e.target.checked })))
                    }
                    className="accent-vault-accent"
                  />
                  <span>{t('import.batch.artist')}</span>
                  <span>{t('import.gallery.title')}</span>
                  <span className="text-right">{t('import.batch.fileCount')}</span>
                </div>
                {/* Table rows */}
                <div className="divide-y divide-vault-border/50">
                  {matches.map((m, idx) => (
                    <div
                      key={m.abs_path}
                      className={`grid grid-cols-[auto_1fr_1fr_auto] gap-2 px-3 py-2 items-center text-sm hover:bg-vault-card-hover transition-colors ${
                        !m.selected ? 'opacity-50' : ''
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={m.selected}
                        onChange={(e) => updateMatch(idx, 'selected', e.target.checked)}
                        className="accent-vault-accent"
                      />
                      <input
                        type="text"
                        value={m.artist ?? ''}
                        onChange={(e) => updateMatch(idx, 'artist', e.target.value || null)}
                        className={editInputClass}
                        placeholder="—"
                      />
                      <input
                        type="text"
                        value={m.title}
                        onChange={(e) => updateMatch(idx, 'title', e.target.value)}
                        className={editInputClass}
                      />
                      <span className="text-xs text-vault-text-muted text-right tabular-nums">
                        {m.file_count}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Unmatched collapsible */}
            {unmatched.length > 0 && (
              <div className="border border-vault-border rounded-lg overflow-hidden">
                <button
                  onClick={() => setUnmatchedOpen((o) => !o)}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-vault-text-muted hover:text-vault-text transition-colors bg-vault-input"
                >
                  <ChevronDown
                    size={13}
                    className={`transition-transform ${unmatchedOpen ? 'rotate-180' : ''}`}
                  />
                  {t('import.batch.unmatchedCount', { count: String(unmatched.length) })}
                </button>
                {unmatchedOpen && (
                  <div className="divide-y divide-vault-border/50">
                    {unmatched.map((u) => (
                      <div key={u.rel_path} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                        <span className="font-mono text-vault-text-muted truncate flex-1">{u.rel_path}</span>
                        <span className="text-vault-text-muted tabular-nums shrink-0">{u.file_count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Import button */}
            {matches.length > 0 && (
              <button
                onClick={handleImport}
                disabled={selectedCount === 0}
                className="w-full px-4 py-2.5 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors"
              >
                {selectedCount === matches.length
                  ? t('import.batch.importAll', { count: String(selectedCount) })
                  : t('import.batch.importSelected', { count: String(selectedCount) })}
              </button>
            )}
          </div>
        )}

        {/* ── importing: progress ── */}
        {phase === 'importing' && progress && (
          <div className="space-y-3">
            <p className="text-sm text-vault-text">
              {t('import.batch.progress', {
                completed: String(progress.completed),
                total: String(progress.total),
              })}
            </p>
            <div className="h-2 bg-vault-border rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{
                  width: progress.total > 0
                    ? `${Math.round((progress.completed / progress.total) * 100)}%`
                    : '0%',
                }}
              />
            </div>
            {progress.failed > 0 && (
              <p className="text-xs text-red-400">
                {t('import.batch.done', {
                  completed: String(progress.completed),
                  failed: String(progress.failed),
                })}
              </p>
            )}
          </div>
        )}

        {/* ── done ── */}
        {phase === 'done' && progress && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Check size={16} className="text-green-400 shrink-0" />
              <p className="text-sm text-vault-text">
                {t('import.batch.done', {
                  completed: String(progress.completed),
                  failed: String(progress.failed),
                })}
              </p>
            </div>
            <button
              onClick={handleReset}
              className="px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-accent/50 text-vault-text rounded text-sm transition-colors"
            >
              {t('import.zoneB.selectFolder')}
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
    <div className="max-w-3xl">
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
  )
}
