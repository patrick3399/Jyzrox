'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Search, Trash2, Radio, Pause, ChevronDown, ChevronUp, Settings2 } from 'lucide-react'
import { useProfile } from '@/hooks/useProfile'
import { useLogs, useLogStream } from '@/hooks/useLogs'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { LogEntry } from '@/lib/types'

const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const
const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'bg-gray-500/20 text-gray-400',
  INFO: 'bg-blue-500/20 text-blue-400',
  WARNING: 'bg-yellow-500/20 text-yellow-400',
  ERROR: 'bg-red-500/20 text-red-400',
  CRITICAL: 'bg-purple-500/20 text-purple-400',
}

function LevelBadge({ level }: { level: string }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${LEVEL_COLORS[level] ?? 'bg-gray-500/20 text-gray-400'}`}>
      {level}
    </span>
  )
}

function LogRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false)
  const ts = new Date(entry.timestamp)
  const timeStr = ts.toLocaleTimeString(undefined, { hour12: false })
  const dateStr = ts.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

  return (
    <div
      className="border-b border-vault-border hover:bg-vault-card-hover transition-colors cursor-pointer"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2 px-4 py-2 text-xs">
        <span className="text-vault-text-muted whitespace-nowrap tabular-nums shrink-0">
          {dateStr} {timeStr}
        </span>
        <LevelBadge level={entry.level} />
        <span className="text-vault-accent shrink-0">{entry.source}</span>
        <span className="text-vault-text-muted shrink-0 hidden sm:inline">{entry.logger}</span>
        <span className="text-vault-text truncate">{entry.message}</span>
        {entry.traceback && (
          <span className="shrink-0 text-vault-text-muted">
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </span>
        )}
      </div>
      {expanded && (
        <div className="px-4 pb-3 space-y-2">
          <pre className="text-xs text-vault-text whitespace-pre-wrap break-all bg-vault-bg rounded p-3 font-mono">
            {entry.message}
          </pre>
          {entry.traceback && (
            <div>
              <p className="text-[10px] font-bold text-vault-text-muted uppercase mb-1">{t('logs.traceback')}</p>
              <pre className="text-xs text-red-400 whitespace-pre-wrap break-all bg-red-500/5 rounded p-3 font-mono">
                {entry.traceback}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function RetentionSettings() {
  const [maxEntries, setMaxEntries] = useState(2000)
  const [open, setOpen] = useState(false)
  const loaded = useRef(false)

  useEffect(() => {
    if (open && !loaded.current) {
      loaded.current = true
      api.logs.getRetention().then(d => {
        setMaxEntries(d.max_entries)
      }).catch(() => {})
    }
  }, [open])

  const save = async () => {
    try {
      await api.logs.setRetention({ max_entries: maxEntries })
      toast.success(t('logs.retentionSaved'))
    } catch {
      toast.error(t('common.error'))
    }
  }

  return (
    <div className="bg-vault-card rounded-lg border border-vault-border">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-vault-card-hover transition-colors"
      >
        <div className="flex items-center gap-2">
          <Settings2 size={14} className="text-vault-text-muted" />
          <span className="text-sm font-medium text-vault-text">{t('logs.retention')}</span>
        </div>
        {open ? <ChevronUp size={14} className="text-vault-text-muted" /> : <ChevronDown size={14} className="text-vault-text-muted" />}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-vault-border pt-3 space-y-3">
          <div className="flex items-center gap-4">
            <label className="text-xs text-vault-text-muted w-28 shrink-0">{t('logs.maxEntries')}</label>
            <input
              type="number"
              min={500}
              max={20000}
              step={1000}
              value={maxEntries}
              onChange={e => setMaxEntries(Number(e.target.value))}
              className="w-24 px-2 py-1 text-sm bg-vault-input border border-vault-border rounded text-vault-text"
            />
          </div>
          <button
            onClick={save}
            className="px-4 py-1.5 bg-vault-accent text-white rounded text-sm font-medium hover:bg-vault-accent/90 transition-colors"
          >
            {t('common.save')}
          </button>
        </div>
      )}
    </div>
  )
}

export default function LogsPage() {
  useLocale()
  const router = useRouter()
  const { data: profile } = useProfile()
  const role = profile?.role
  const [selectedLevels, setSelectedLevels] = useState<string[]>([])
  const [source, setSource] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [realTime, setRealTime] = useState(false)
  const [offset, setOffset] = useState(0)
  const limit = 100

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    setOffset(0)
  }, [selectedLevels, source, debouncedSearch])

  const params = {
    level: selectedLevels.length > 0 ? selectedLevels : undefined,
    source: source || undefined,
    search: debouncedSearch || undefined,
    limit,
    offset,
  }

  const { logs, total, hasMore, isLoading, mutate } = useLogs(params)
  const { streamedLogs, clearStream, isPaused, togglePause } = useLogStream()

  useEffect(() => {
    if (role && role !== 'admin') router.replace('/')
  }, [role, router])

  const toggleLevel = (level: string) => {
    setSelectedLevels(prev =>
      prev.includes(level) ? prev.filter(l => l !== level) : [...prev, level]
    )
  }

  const clearLogs = async () => {
    if (!window.confirm(t('logs.clearConfirm'))) return
    try {
      await api.logs.clear()
      toast.success(t('logs.cleared'))
      mutate()
      clearStream()
    } catch {
      toast.error(t('common.error'))
    }
  }

  const displayLogs = realTime ? streamedLogs : logs

  if (role && role !== 'admin') return null

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-4">
      <h1 className="text-xl font-bold text-vault-text">{t('logs.title')}</h1>

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {LEVELS.map(level => (
          <button
            key={level}
            onClick={() => toggleLevel(level)}
            className={`px-2 py-1 rounded text-[11px] font-bold uppercase transition-all ${
              selectedLevels.includes(level) || selectedLevels.length === 0
                ? LEVEL_COLORS[level]
                : 'bg-vault-border/30 text-vault-text-muted opacity-40'
            }`}
          >
            {level}
          </button>
        ))}

        <div className="w-px h-6 bg-vault-border mx-1" />

        <select
          value={source}
          onChange={e => setSource(e.target.value)}
          className="px-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text"
        >
          <option value="">{t('logs.allSources')}</option>
          <option value="api">{t('settings.logLevelApi')}</option>
          <option value="worker">{t('settings.logLevelWorker')}</option>
        </select>

        <div className="relative flex-1 min-w-[150px] max-w-xs">
          <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-vault-text-muted" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={t('logs.filterSearch')}
            className="w-full pl-7 pr-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text placeholder:text-vault-text-muted"
          />
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={() => { setRealTime(!realTime); if (!realTime) clearStream() }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              realTime
                ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                : 'bg-vault-input border border-vault-border text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            <Radio size={12} />
            {t('logs.realTime')}
          </button>

          {realTime && (
            <button
              onClick={togglePause}
              className={`flex items-center gap-1 px-2 py-1.5 rounded text-xs border transition-colors ${
                isPaused
                  ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                  : 'bg-vault-input border-vault-border text-vault-text-secondary'
              }`}
            >
              <Pause size={12} />
              {isPaused ? t('logs.paused') : t('logs.paused')}
            </button>
          )}

          <button
            onClick={clearLogs}
            className="flex items-center gap-1 px-2 py-1.5 rounded text-xs bg-vault-input border border-vault-border text-vault-text-secondary hover:text-red-400 hover:border-red-500/30 transition-colors"
          >
            <Trash2 size={12} />
            {t('logs.clearLogs')}
          </button>
        </div>
      </div>

      {!realTime && (
        <p className="text-xs text-vault-text-muted">{t('logs.entries', { count: String(total) })}</p>
      )}

      <div className="bg-vault-card rounded-lg border border-vault-border overflow-hidden">
        {displayLogs.length === 0 ? (
          <div className="px-4 py-12 text-center text-vault-text-muted text-sm">
            {isLoading ? '...' : t('logs.noLogs')}
          </div>
        ) : (
          displayLogs.map((entry, i) => <LogRow key={`${entry.timestamp}-${i}`} entry={entry} />)
        )}
      </div>

      {!realTime && hasMore && (
        <div className="flex justify-center">
          <button
            onClick={() => setOffset(prev => prev + limit)}
            disabled={isLoading}
            className="px-4 py-2 bg-vault-input border border-vault-border rounded text-sm text-vault-text-secondary hover:text-vault-text transition-colors disabled:opacity-50"
          >
            {t('logs.showMore')}
          </button>
        </div>
      )}

      <RetentionSettings />
    </div>
  )
}
