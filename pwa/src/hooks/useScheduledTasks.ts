'use client'
import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useScheduledTasks(refreshInterval?: number) {
  return useSWR('scheduled-tasks', () => api.scheduledTasks.list(), {
    refreshInterval,
  })
}

export function useUpdateTask() {
  return useSWRMutation('scheduled-tasks', (_key: string, { arg }: { arg: { taskId: string; data: { enabled?: boolean; cron_expr?: string } } }) =>
    api.scheduledTasks.update(arg.taskId, arg.data)
  )
}

export function useRunTask() {
  return useSWRMutation('scheduled-tasks', (_key: string, { arg }: { arg: string }) =>
    api.scheduledTasks.run(arg)
  )
}
