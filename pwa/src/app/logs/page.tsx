'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Search, Trash2, Radio, Pause } from 'lucide-react'
import { useProfile } from '@/hooks/useProfile'
import { useLogs, useLogStream } from '@/hooks/useLogs'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { LEVEL_COLORS, LogRow, RetentionSettings } from '@/components/logs/LogParts'

const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const
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
    setSelectedLevels((prev) =>
      prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level],
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
    <PageContainer variant="secondary" className="space-y-4">
      <PageHeader title={t('logs.title')} spacing="none" />

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {LEVELS.map((level) => (
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
          onChange={(e) => setSource(e.target.value)}
          className="px-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text"
        >
          <option value="">{t('logs.allSources')}</option>
          <option value="api">{t('settings.logLevelApi')}</option>
          <option value="worker">{t('settings.logLevelWorker')}</option>
        </select>

        <div className="relative flex-1 min-w-[150px] max-w-xs">
          <Search
            size={14}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-vault-text-muted"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('logs.filterSearch')}
            className="w-full pl-7 pr-2 py-1.5 text-xs bg-vault-input border border-vault-border rounded text-vault-text placeholder:text-vault-text-muted"
          />
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={() => {
              setRealTime(!realTime)
              if (!realTime) clearStream()
            }}
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

          <Button
            variant="secondary"
            size="sm"
            onClick={clearLogs}
            className="text-xs hover:text-red-400 hover:border-red-500/30"
          >
            <Trash2 size={12} />
            {t('logs.clearLogs')}
          </Button>
        </div>
      </div>

      {!realTime && (
        <p className="text-xs text-vault-text-muted">
          {t('logs.entries', { count: String(total) })}
        </p>
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
          <Button
            variant="secondary"
            onClick={() => setOffset((prev) => prev + limit)}
            disabled={isLoading}
          >
            {t('logs.showMore')}
          </Button>
        </div>
      )}

      <RetentionSettings />
    </PageContainer>
  )
}
