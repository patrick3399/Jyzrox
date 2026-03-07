import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { JobListParams } from '@/lib/types'

export function useDownloadJobs(params: JobListParams = {}) {
  return useSWR(
    ['download/jobs', params],
    () => api.download.getJobs(params),
    { refreshInterval: 3000 }   // Poll every 3s for live updates
  )
}

export function useEnqueueDownload() {
  return useSWRMutation(
    'download/enqueue',
    (_key: unknown, { arg }: { arg: { url: string; source?: string } }) =>
      api.download.enqueue(arg.url, arg.source ?? '')
  )
}

export function useCancelJob() {
  return useSWRMutation(
    'download/cancel',
    (_key: unknown, { arg }: { arg: string }) =>
      api.download.cancelJob(arg)
  )
}
