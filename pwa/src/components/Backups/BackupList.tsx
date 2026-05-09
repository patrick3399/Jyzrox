'use client'

import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { Database, Download, Play, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { DatabaseBackup as DatabaseBackupRecord } from '@/lib/types'

function formatSize(bytes: number | null): string {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function formatDate(value: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function statusClass(status: string, exists: boolean): string {
  if (!exists) return 'text-yellow-400'
  if (status === 'ok') return 'text-green-400'
  if (status === 'failed') return 'text-red-400'
  return 'text-vault-text-muted'
}

function BackupRow({
  backup,
  onDelete,
}: {
  backup: DatabaseBackupRecord
  onDelete: (id: string) => Promise<void>
}) {
  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-3 items-center px-3 py-2 border-b border-vault-border last:border-b-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Database size={14} className="text-vault-text-muted shrink-0" />
          <span className="text-sm text-vault-text truncate">{backup.filename ?? backup.id}</span>
        </div>
        <div className="mt-0.5 text-[10px] text-vault-text-muted truncate">
          {formatDate(backup.created_at)} · {backup.app_version ?? 'unknown'}
        </div>
      </div>
      <span className={`text-xs ${statusClass(backup.status, backup.exists)}`}>
        {backup.exists ? backup.status : t('backups.missingFile')}
      </span>
      <span className="text-xs text-vault-text-muted tabular-nums">{formatSize(backup.size_bytes)}</span>
      {backup.exists ? (
        <a
          href={`/api/admin/backups/${encodeURIComponent(backup.id)}/download`}
          download={backup.filename ?? backup.id}
          className="p-1.5 rounded text-vault-text-muted hover:text-vault-accent hover:bg-vault-accent/10"
          aria-label={t('backups.download')}
        >
          <Download size={14} />
        </a>
      ) : (
        <span className="p-1.5" />
      )}
      <button
        type="button"
        onClick={() => onDelete(backup.id)}
        className="p-1.5 rounded text-vault-text-muted hover:text-red-400 hover:bg-red-500/10"
        aria-label={t('backups.delete')}
      >
        <Trash2 size={14} />
      </button>
    </div>
  )
}

export function BackupList() {
  const { data, error, isLoading, mutate } = useSWR('admin-backups', () => api.backups.list())
  const runBackup = useSWRMutation('admin-backups', () => api.backups.run())

  async function handleRun() {
    try {
      await runBackup.trigger()
      toast.success(t('backups.runQueued'))
      await mutate()
    } catch {
      toast.error(t('backups.runFailed'))
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm(t('backups.deleteConfirm'))) return
    try {
      await api.backups.delete(id)
      toast.success(t('backups.deleted'))
      await mutate()
    } catch {
      toast.error(t('backups.deleteFailed'))
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-vault-text">{t('backups.title')}</h2>
          <p className="text-xs text-vault-text-muted">{data?.path ?? t('backups.loadingPath')}</p>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={runBackup.isMutating}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-vault-accent/10 text-vault-accent text-xs font-medium hover:bg-vault-accent/20 disabled:opacity-50"
        >
          <Play size={14} />
          {t('backups.runNow')}
        </button>
      </div>

      <div className="bg-vault-input border border-vault-border rounded-lg overflow-hidden">
        {isLoading && <div className="p-3 text-sm text-vault-text-muted">{t('common.loading')}</div>}
        {error && <div className="p-3 text-sm text-red-400">{t('backups.loadFailed')}</div>}
        {!isLoading && !error && (data?.backups.length ?? 0) === 0 && (
          <div className="p-3 text-sm text-vault-text-muted">{t('backups.empty')}</div>
        )}
        {data?.backups.map((backup) => (
          <BackupRow key={backup.id} backup={backup} onDelete={handleDelete} />
        ))}
      </div>
    </section>
  )
}
