import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { JobListParams } from '@/lib/types'

export function useDownloadJobs(params: JobListParams = {}) {
  return useSWR(
    ['download/jobs', params],
    () => api.download.getJobs(params),
    { refreshInterval: 3000, dedupingInterval: 2000, focusThrottleInterval: 5000 }
  )
}

export function useEnqueueDownload() {
  return useSWRMutation(
    'download/enqueue',
    (_key: unknown, { arg }: { arg: { url: string } }) =>
      api.download.enqueue(arg.url)
  )
}

export function useCancelJob() {
  return useSWRMutation(
    'download/cancel',
    (_key: unknown, { arg }: { arg: string }) =>
      api.download.cancelJob(arg)
  )
}
