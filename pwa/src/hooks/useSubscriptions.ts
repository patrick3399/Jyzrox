import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useSubscriptions(
  params: { source?: string; enabled?: boolean; limit?: number; offset?: number } = {},
) {
  const key = ['subscriptions', JSON.stringify(params)]
  return useSWR(key, () => api.subscriptions.list(params))
}

export function useCreateSubscription() {
  return useSWRMutation(
    'subscriptions',
    (
      _key: string,
      {
        arg,
      }: {
        arg: {
          url: string
          name?: string
          cron_expr?: string
          auto_download?: boolean
          group_id?: number | null
        }
      },
    ) => api.subscriptions.create(arg),
  )
}

export function useUpdateSubscription() {
  return useSWRMutation(
    'subscriptions',
    (
      _key: string,
      {
        arg,
      }: {
        arg: {
          id: number
          data: {
            name?: string
            enabled?: boolean
            auto_download?: boolean
            cron_expr?: string
            group_id?: number | null
          }
        }
      },
    ) => api.subscriptions.update(arg.id, arg.data),
  )
}

export function useDeleteSubscription() {
  return useSWRMutation('subscriptions', (_key: string, { arg }: { arg: number }) =>
    api.subscriptions.delete(arg),
  )
}

export function useCheckSubscription() {
  return useSWRMutation('subscriptions', (_key: string, { arg }: { arg: number }) =>
    api.subscriptions.check(arg),
  )
}

export function useSubscriptionJobs(subId: number | null) {
  return useSWR(subId ? ['subscription-jobs', subId] : null, () => api.subscriptions.jobs(subId!), {
    refreshInterval: 5000,
  })
}
