'use client'

import { useState, useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { Settings2, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { LogEntry } from '@/lib/types'
import { Button } from '@/components/ui/button'

export const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'bg-gray-500/20 text-gray-400',
  INFO: 'bg-blue-500/20 text-blue-400',
  WARNING: 'bg-yellow-500/20 text-yellow-400',
  ERROR: 'bg-red-500/20 text-red-400',
  CRITICAL: 'bg-purple-500/20 text-purple-400',
}

function LevelBadge({ level }: { level: string }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${LEVEL_COLORS[level] ?? 'bg-gray-500/20 text-gray-400'}`}
    >
      {level}
    </span>
  )
}

export function LogRow({ entry }: { entry: LogEntry }) {
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
              <p className="text-[10px] font-bold text-vault-text-muted uppercase mb-1">
                {t('logs.traceback')}
              </p>
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

export function RetentionSettings() {
  const [maxEntries, setMaxEntries] = useState(2000)
  const [open, setOpen] = useState(false)
  const loaded = useRef(false)

  useEffect(() => {
    if (open && !loaded.current) {
      loaded.current = true
      api.logs
        .getRetention()
        .then((d) => {
          setMaxEntries(d.max_entries)
        })
        .catch(() => {})
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
        {open ? (
          <ChevronUp size={14} className="text-vault-text-muted" />
        ) : (
          <ChevronDown size={14} className="text-vault-text-muted" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-vault-border pt-3 space-y-3">
          <div className="flex items-center gap-4">
            <label className="text-xs text-vault-text-muted w-28 shrink-0">
              {t('logs.maxEntries')}
            </label>
            <input
              type="number"
              min={500}
              max={20000}
              step={1000}
              value={maxEntries}
              onChange={(e) => setMaxEntries(Number(e.target.value))}
              className="w-24 px-2 py-1 text-sm bg-vault-input border border-vault-border rounded text-vault-text"
            />
          </div>
          <Button variant="primary" size="sm" onClick={save}>
            {t('common.save')}
          </Button>
        </div>
      )}
    </div>
  )
}
