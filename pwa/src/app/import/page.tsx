'use client'

import { useState } from 'react'
import {
  Folder,
  File,
  ChevronRight,
  Home,
  FolderInput,
  Link2,
  Copy,
  ArrowLeft,
  Search,
  HardDrive,
  CircleDot,
} from 'lucide-react'
import { toast } from 'sonner'
import { mutate } from 'swr'
import {
  useBrowseDirectory,
  useRecentImports,
  useImportProgress,
  useStartImport,
  useLibraries,
  useMonitorStatus,
  useAutoDiscover,
} from '@/hooks/useImport'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'

// ── Progress bar for active import ───────────────────────────────────

function ActiveImportRow({ galleryId }: { galleryId: number }) {
  const { data } = useImportProgress(galleryId)
  if (!data) return null

  const pct =
    data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0
  const isDone = data.status === 'done' || data.status === 'imported'

  return (
    <div className="bg-vault-input border border-vault-border rounded-lg px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-vault-text">
          {t('import.progress', { processed: data.processed, total: data.total })}
        </span>
        <span
          className={`text-xs font-medium ${isDone ? 'text-green-400' : 'text-blue-400'}`}
        >
          {isDone ? '100%' : `${pct}%`}
        </span>
      </div>
      <div className="h-1.5 bg-vault-border rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${isDone ? 'bg-green-500' : 'bg-blue-500'}`}
          style={{ width: `${isDone ? 100 : pct}%` }}
        />
      </div>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
  running: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
  importing: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
  done: 'bg-green-500/10 border-green-500/30 text-green-400',
  imported: 'bg-green-500/10 border-green-500/30 text-green-400',
  failed: 'bg-red-500/10 border-red-500/30 text-red-400',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${STATUS_STYLES[status] ?? 'bg-vault-card border-vault-border text-vault-text-muted'}`}
    >
      {status}
    </span>
  )
}

// ── Main page ─────────────────────────────────────────────────────────

export default function ImportPage() {
  const [currentPath, setCurrentPath] = useState('')
  const [selectedDir, setSelectedDir] = useState<string | null>(null)
  const [importMode, setImportMode] = useState<'link' | 'copy'>('link')
  const [titleInput, setTitleInput] = useState('')
  const [activeImports, setActiveImports] = useState<number[]>([])
  const [selectedLibrary, setSelectedLibrary] = useState('')

  const { data: libraries } = useLibraries()
  const { data: monitorData } = useMonitorStatus()
  const { trigger: discover, isMutating: discovering } = useAutoDiscover()
  const { data: browseData, isLoading: browseLoading } = useBrowseDirectory(currentPath, selectedLibrary)
  const { data: recentData } = useRecentImports()
  const { trigger: startImport, isMutating: importing } = useStartImport()

  // Build breadcrumb segments from currentPath
  const pathSegments = currentPath ? currentPath.split('/').filter(Boolean) : []

  const navigateTo = (path: string) => {
    setCurrentPath(path)
    setSelectedDir(null)
    setTitleInput('')
  }

  const navigateUp = () => {
    const segments = pathSegments.slice(0, -1)
    navigateTo(segments.join('/'))
  }

  const handleLibraryChange = (libPath: string) => {
    setSelectedLibrary(libPath)
    setCurrentPath('')
    setSelectedDir(null)
  }

  const handleDiscover = async () => {
    try {
      await discover()
      toast.success(t('import.discover.started'))
      setTimeout(() => mutate('import/recent'), 5000)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const handleDirClick = (name: string, type: string) => {
    if (type === 'dir') {
      const next = currentPath ? `${currentPath}/${name}` : name
      setSelectedDir(null)
      setTitleInput('')
      navigateTo(next)
    }
  }

  const handleSelectDir = (name: string) => {
    const full = currentPath ? `${currentPath}/${name}` : name
    setSelectedDir(full)
    setTitleInput(name)
  }

  const handleStartImport = async () => {
    if (!selectedDir) return
    try {
      const result = await startImport({
        sourceDir: selectedDir,
        mode: importMode,
        title: titleInput.trim() || undefined,
      })
      toast.success(t('import.importing'))
      setActiveImports((prev) => [...prev, result.gallery_id])
      setSelectedDir(null)
      setTitleInput('')
      // Refresh recent imports after a short delay
      setTimeout(() => mutate('import/recent'), 3000)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const entries = browseData?.entries ?? []
  const dirs = entries.filter((e) => e.type === 'dir')
  const files = entries.filter((e) => e.type === 'file')

  const inputClass =
    'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'

  return (
    <div className="min-h-screen bg-vault-bg text-vault-text">
      <div className="max-w-3xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <FolderInput size={22} className="text-vault-accent shrink-0" />
          <h1 className="text-2xl font-bold text-vault-text">{t('import.title')}</h1>
          <div className="ml-auto flex items-center gap-2">
            {/* Monitor status dot */}
            {monitorData && (
              <span
                className="flex items-center gap-1 text-xs text-vault-text-muted"
                title={monitorData.running ? t('import.monitor.active') : t('import.monitor.inactive')}
              >
                <CircleDot
                  size={12}
                  className={monitorData.running ? 'text-green-400' : 'text-vault-text-muted'}
                />
                {monitorData.running ? t('import.monitor.active') : t('import.monitor.inactive')}
              </span>
            )}
            {/* Auto-discover button */}
            <button
              onClick={handleDiscover}
              disabled={discovering}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-vault-input border border-vault-border hover:border-vault-accent/50 text-vault-text-secondary hover:text-vault-text rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
            >
              <Search size={13} />
              {discovering ? t('import.discover.running') : t('import.discover')}
            </button>
          </div>
        </div>

        {/* Library paths selector */}
        {libraries && libraries.length > 1 && (
          <div className="flex gap-1.5 mb-4 overflow-x-auto pb-1">
            {libraries
              .filter((l) => l.enabled)
              .map((lib) => (
                <button
                  key={lib.path}
                  onClick={() => handleLibraryChange(lib.path)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                    selectedLibrary === lib.path ||
                    (!selectedLibrary && lib.is_primary)
                      ? 'bg-vault-accent text-white'
                      : 'bg-vault-input border border-vault-border text-vault-text-muted hover:text-vault-text hover:border-vault-accent/50'
                  }`}
                >
                  <HardDrive size={12} />
                  {lib.label}
                  {!lib.exists && (
                    <span className="text-red-400 text-[10px]">!</span>
                  )}
                </button>
              ))}
          </div>
        )}

        {/* Active Imports */}
        {activeImports.length > 0 && (
          <div className="mb-6">
            <h2 className="text-sm font-medium text-vault-text-secondary uppercase tracking-wide mb-3">
              {t('import.active')}
            </h2>
            <div className="space-y-2">
              {activeImports.map((id) => (
                <ActiveImportRow key={id} galleryId={id} />
              ))}
            </div>
          </div>
        )}

        {/* Directory Browser */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-4">
          {/* Header row with breadcrumbs */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-vault-border bg-vault-card/50 flex-wrap">
            <button
              onClick={() => navigateTo('')}
              className="flex items-center gap-1 text-sm text-vault-text-muted hover:text-vault-accent transition-colors shrink-0"
              title={t('import.breadcrumb.root')}
            >
              <Home size={14} />
              <span>{t('import.breadcrumb.root')}</span>
            </button>
            {pathSegments.map((seg, idx) => {
              const segPath = pathSegments.slice(0, idx + 1).join('/')
              const isLast = idx === pathSegments.length - 1
              return (
                <span key={segPath} className="flex items-center gap-1 min-w-0">
                  <ChevronRight size={12} className="text-vault-text-muted shrink-0" />
                  {isLast ? (
                    <span className="text-sm text-vault-text font-medium truncate max-w-[180px]">
                      {seg}
                    </span>
                  ) : (
                    <button
                      onClick={() => navigateTo(segPath)}
                      className="text-sm text-vault-text-muted hover:text-vault-accent transition-colors truncate max-w-[120px]"
                    >
                      {seg}
                    </button>
                  )}
                </span>
              )
            })}
            {pathSegments.length > 0 && (
              <button
                onClick={navigateUp}
                className="ml-auto flex items-center gap-1 text-xs text-vault-text-muted hover:text-vault-text transition-colors shrink-0"
              >
                <ArrowLeft size={12} />
                {t('common.goBack')}
              </button>
            )}
          </div>

          {/* Directory listing */}
          <div className="divide-y divide-vault-border/50">
            {browseLoading ? (
              <div className="flex justify-center py-10">
                <LoadingSpinner />
              </div>
            ) : dirs.length === 0 && files.length === 0 ? (
              <div className="py-10 text-center text-vault-text-muted text-sm">
                {t('import.dir.empty')}
              </div>
            ) : (
              <>
                {dirs.map((entry) => (
                  <div
                    key={entry.name}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-vault-card-hover transition-colors group"
                  >
                    <button
                      onClick={() => handleDirClick(entry.name, entry.type)}
                      className="flex items-center gap-3 flex-1 min-w-0 text-left"
                    >
                      <Folder size={16} className="text-yellow-400/80 shrink-0" />
                      <span className="text-sm text-vault-text truncate flex-1">
                        {entry.name}
                      </span>
                      {entry.file_count !== undefined && entry.file_count > 0 && (
                        <span className="text-xs text-vault-text-muted shrink-0">
                          {t('import.dir.files', { count: entry.file_count })}
                        </span>
                      )}
                      <ChevronRight
                        size={14}
                        className="text-vault-text-muted shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      />
                    </button>
                    {entry.file_count !== undefined && entry.file_count > 0 && (
                      <button
                        onClick={() => handleSelectDir(entry.name)}
                        className={`shrink-0 text-xs px-2.5 py-1 rounded border transition-colors ${
                          selectedDir ===
                          (currentPath ? `${currentPath}/${entry.name}` : entry.name)
                            ? 'bg-vault-accent text-white border-vault-accent'
                            : 'bg-vault-input border-vault-border text-vault-text-secondary hover:border-vault-accent/50 hover:text-vault-accent'
                        }`}
                      >
                        {t('import.start')}
                      </button>
                    )}
                  </div>
                ))}
                {files.length > 0 && (
                  <div className="px-4 py-2 flex items-center gap-2 text-xs text-vault-text-muted">
                    <File size={12} />
                    <span>{t('import.dir.files', { count: files.length })}</span>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Import options panel — shown when a dir is selected */}
        {selectedDir && (
          <div className="bg-vault-card border border-vault-accent/30 rounded-xl p-5 mb-4 space-y-4">
            <div>
              <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">
                {t('import.browse')}
              </p>
              <p className="text-sm text-vault-text font-mono truncate">{selectedDir}</p>
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

            {/* Mode toggle */}
            <div>
              <label className="block text-xs text-vault-text-muted mb-2">
                {t('import.mode')}
              </label>
              <div className="flex rounded overflow-hidden border border-vault-border bg-vault-input">
                <button
                  onClick={() => setImportMode('link')}
                  className={`flex-1 flex flex-col items-center gap-0.5 px-4 py-2.5 text-sm transition-colors ${
                    importMode === 'link'
                      ? 'bg-vault-accent text-white'
                      : 'text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  <span className="flex items-center gap-1.5 font-medium">
                    <Link2 size={14} />
                    {t('import.mode.link')}
                  </span>
                  <span className="text-[11px] opacity-70">{t('import.mode.link.desc')}</span>
                </button>
                <button
                  onClick={() => setImportMode('copy')}
                  className={`flex-1 flex flex-col items-center gap-0.5 px-4 py-2.5 text-sm transition-colors border-l border-vault-border ${
                    importMode === 'copy'
                      ? 'bg-vault-accent text-white'
                      : 'text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  <span className="flex items-center gap-1.5 font-medium">
                    <Copy size={14} />
                    {t('import.mode.copy')}
                  </span>
                  <span className="text-[11px] opacity-70">{t('import.mode.copy.desc')}</span>
                </button>
              </div>
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

        {/* Recent Imports */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-vault-border">
            <h2 className="text-sm font-medium text-vault-text">{t('import.recent')}</h2>
          </div>
          <div className="divide-y divide-vault-border/50">
            {!recentData ? (
              <div className="flex justify-center py-8">
                <LoadingSpinner />
              </div>
            ) : recentData.length === 0 ? (
              <div className="py-8 text-center text-sm text-vault-text-muted">
                {t('import.no.recent')}
              </div>
            ) : (
              recentData.map((item) => (
                <div key={item.id} className="flex items-center gap-3 px-4 py-3">
                  <Folder size={15} className="text-vault-text-muted shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-vault-text truncate">{item.title}</p>
                    <p className="text-xs text-vault-text-muted mt-0.5">
                      {t('import.pages', { count: item.pages })}
                      {' · '}
                      {new Date(item.added_at).toLocaleDateString()}
                    </p>
                  </div>
                  <StatusBadge status={item.status} />
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
