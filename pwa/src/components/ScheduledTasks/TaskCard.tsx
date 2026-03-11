'use client'
import { useState } from 'react'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { StatusBadge } from './StatusBadge'
import { timeAgo } from '@/lib/timeUtils'
import type { ScheduledTask } from '@/lib/types'

interface TaskCardProps {
  task: ScheduledTask
  onToggle: (taskId: string, enabled: boolean) => Promise<void>
  onCronUpdate: (taskId: string, cron: string) => Promise<void>
  onReset: (taskId: string) => Promise<void>
  onRunNow: (taskId: string) => Promise<void>
}

const CRON_PRESETS = [
  { label: () => t('settings.tasks.presetEveryHour'), value: '0 * * * *' },
  { label: () => t('settings.tasks.presetEvery2Hours'), value: '0 */2 * * *' },
  { label: () => t('settings.tasks.presetDaily2am'), value: '0 2 * * *' },
  { label: () => t('settings.tasks.presetWeeklyMon3am'), value: '0 3 * * 1' },
]

export function TaskCard({ task, onToggle, onCronUpdate, onReset, onRunNow }: TaskCardProps) {
  const [editingCron, setEditingCron] = useState<string | undefined>(undefined)
  const [showError, setShowError] = useState(false)

  const cronValue = editingCron ?? task.cron_expr
  const isRunning = task.last_status === 'running'
  const canReset = task.cron_expr !== task.default_cron

  const handleCronBlur = () => {
    if (editingCron !== undefined && editingCron !== task.cron_expr) {
      onCronUpdate(task.id, editingCron)
    }
  }

  const handleCronKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && editingCron !== undefined) {
      e.preventDefault()
      void onCronUpdate(task.id, editingCron)
      setEditingCron(undefined)
    }
  }

  const ago = timeAgo(task.last_run)

  return (
    <div className="bg-vault-input border border-vault-border rounded-lg p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-vault-text">{task.name}</span>
            <StatusBadge status={task.last_status} />
          </div>
          <p className="text-xs text-vault-text-muted mb-2">{task.description}</p>

          {/* Cron expression + presets */}
          <div className="flex flex-wrap items-center gap-1.5 mb-2">
            <input
              type="text"
              value={cronValue}
              onChange={(e) => setEditingCron(e.target.value)}
              onBlur={handleCronBlur}
              onKeyDown={handleCronKeyDown}
              className="w-32 px-2 py-1 bg-vault-bg border border-vault-border rounded text-xs text-vault-text font-mono"
              disabled={!task.enabled}
            />
            {CRON_PRESETS.map((p) => (
              <button
                key={p.value}
                onClick={() => onCronUpdate(task.id, p.value)}
                disabled={!task.enabled}
                className={`px-2 py-1 rounded text-[10px] transition-colors ${
                  task.cron_expr === p.value
                    ? 'bg-vault-accent/20 text-vault-accent'
                    : 'bg-vault-bg border border-vault-border text-vault-text-muted hover:text-vault-text disabled:opacity-40'
                }`}
              >
                {p.label()}
              </button>
            ))}
            {canReset && (
              <button
                onClick={() => onReset(task.id)}
                className="px-2 py-1 rounded text-[10px] transition-colors bg-vault-bg border border-vault-border text-yellow-400 hover:text-yellow-300"
              >
                {t('scheduledTasks.resetToDefault')}
              </button>
            )}
          </div>

          {/* Default cron hint */}
          <p className="text-[10px] text-vault-text-muted mb-1">
            {t('scheduledTasks.defaultCron', { cron: task.default_cron })}
          </p>

          {/* Last run info */}
          {ago && (
            <p className="text-[10px] text-vault-text-muted">
              {t('scheduledTasks.lastRunAgo', { time: ago })}
            </p>
          )}

          {/* Error block */}
          {task.last_error && (
            <div className="mt-1">
              <button
                onClick={() => setShowError((v) => !v)}
                className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
              >
                {showError ? t('scheduledTasks.hideError') : t('scheduledTasks.showError')}
              </button>
              {showError && (
                <pre className="mt-1 text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded p-2 overflow-x-auto whitespace-pre-wrap break-words">
                  <code>{task.last_error}</code>
                </pre>
              )}
            </div>
          )}
        </div>

        {/* Right controls */}
        <div className="flex flex-col items-end gap-2 shrink-0">
          {/* Enable toggle */}
          <button
            onClick={() => onToggle(task.id, task.enabled)}
            aria-label={task.enabled ? t('settings.tasks.disableTask') : t('settings.tasks.enableTask')}
            aria-pressed={task.enabled}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
              task.enabled ? 'bg-green-600' : 'bg-vault-border'
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                task.enabled ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>

          {/* Run Now button */}
          <button
            onClick={() => onRunNow(task.id)}
            disabled={isRunning}
            className="px-2 py-1 rounded text-[10px] font-medium bg-vault-accent/10 text-vault-accent hover:bg-vault-accent/20 transition-colors disabled:opacity-50 flex items-center gap-1"
          >
            {isRunning && <LoadingSpinner size="sm" />}
            {t('settings.tasks.runNow')}
          </button>
        </div>
      </div>
    </div>
  )
}
