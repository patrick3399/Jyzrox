'use client'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { TaskCard } from './TaskCard'
import { useScheduledTasks, useUpdateTask, useRunTask } from '@/hooks/useScheduledTasks'

interface TaskListProps {
  pollWhileRunning?: boolean
}

export function TaskList({ pollWhileRunning = true }: TaskListProps) {
  const [refreshInterval, setRefreshInterval] = useState(0)

  const { data: tasksData, isLoading, mutate } = useScheduledTasks(refreshInterval)
  const { trigger: updateTask } = useUpdateTask()
  const { trigger: runTask } = useRunTask()

  const tasks = tasksData?.tasks ?? []
  const hasRunning = tasks.some((task) => task.last_status === 'running')

  useEffect(() => {
    if (!pollWhileRunning) return
    setRefreshInterval(hasRunning ? 3000 : 0)
  }, [hasRunning, pollWhileRunning])

  const handleToggle = async (taskId: string, enabled: boolean) => {
    try {
      await updateTask({ taskId, data: { enabled: !enabled } })
      mutate()
      toast.success(t('settings.tasks.updated'))
    } catch {
      toast.error(t('settings.tasks.updateFailed'))
    }
  }

  const handleCronUpdate = async (taskId: string, cron: string) => {
    try {
      await updateTask({ taskId, data: { cron_expr: cron } })
      mutate()
      toast.success(t('settings.tasks.updated'))
    } catch {
      toast.error(t('settings.tasks.updateFailed'))
    }
  }

  const handleReset = async (taskId: string) => {
    const task = tasks.find((task) => task.id === taskId)
    if (!task) return
    try {
      await updateTask({ taskId, data: { cron_expr: task.default_cron } })
      mutate()
      toast.success(t('settings.tasks.updated'))
    } catch {
      toast.error(t('settings.tasks.updateFailed'))
    }
  }

  const handleRunNow = async (taskId: string) => {
    try {
      await runTask(taskId)
      mutate()
      toast.success(t('settings.tasks.queued'))
    } catch {
      toast.error(t('settings.tasks.queueFailed'))
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <LoadingSpinner />
      </div>
    )
  }

  if (tasks.length === 0) {
    return (
      <p className="text-sm text-vault-text-muted text-center py-8">
        {t('scheduledTasks.noTasks')}
      </p>
    )
  }

  const libraryScanTask = tasks.find((task) => task.id === 'library_scan')
  const otherTasks = tasks.filter((task) => task.id !== 'library_scan')

  return (
    <div className="space-y-6">
      {libraryScanTask && (
        <section className="space-y-2">
          <div>
            <h2 className="text-base font-semibold text-vault-text">
              {t('scheduledTasks.externalFolderScan')}
            </h2>
            <p className="text-xs text-vault-text-muted">
              {t('scheduledTasks.externalFolderScanDesc')}
            </p>
          </div>
          <TaskCard
            task={libraryScanTask}
            featured
            onToggle={handleToggle}
            onCronUpdate={handleCronUpdate}
            onReset={handleReset}
            onRunNow={handleRunNow}
          />
        </section>
      )}

      {otherTasks.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-vault-text">
            {t('scheduledTasks.otherTasks')}
          </h2>
          {otherTasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onToggle={handleToggle}
              onCronUpdate={handleCronUpdate}
              onReset={handleReset}
              onRunNow={handleRunNow}
            />
          ))}
        </section>
      )}
    </div>
  )
}
