import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'
import type { Subscription } from '@/lib/types'

export function useSubscriptions(
  params: { source?: string; enabled?: boolean; limit?: number; offset?: number } = {},
) {
  const key = ['subscriptions', JSON.stringify(params)]
  return useSWR(key, () => api.subscriptions.list(params))
}

/** The API caps one page at 200 rows. */
export const SUBSCRIPTION_PAGE_SIZE = 200

/**
 * Every subscription of the current user, fetched page by page so the list is
 * not silently cut at the API's per-page cap. Rows are de-duplicated by id in
 * case a subscription created mid-fetch shifts the offsets.
 */
export async function fetchAllSubscriptions(
  listPage: typeof api.subscriptions.list = api.subscriptions.list,
): Promise<{ subscriptions: Subscription[]; total: number }> {
  const byId = new Map<number, Subscription>()
  let total = 0
  for (let offset = 0; offset === 0 || offset < total; offset += SUBSCRIPTION_PAGE_SIZE) {
    const page = await listPage({ limit: SUBSCRIPTION_PAGE_SIZE, offset })
    total = page.total
    for (const sub of page.subscriptions) if (!byId.has(sub.id)) byId.set(sub.id, sub)
    if (page.subscriptions.length < SUBSCRIPTION_PAGE_SIZE) break
  }
  return { subscriptions: [...byId.values()], total: byId.size }
}

export function useAllSubscriptions() {
  return useSWR(['subscriptions', 'all'], () => fetchAllSubscriptions())
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
          download_options?: Record<string, unknown>
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
            download_options?: Record<string, unknown>
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

export function useBackfillSubscription() {
  return useSWRMutation('subscriptions', (_key: string, { arg }: { arg: number }) =>
    api.subscriptions.backfill(arg),
  )
}

export function useSubscriptionJobs(subId: number | null) {
  return useSWR(subId ? ['subscription-jobs', subId] : null, () => api.subscriptions.jobs(subId!), {
    refreshInterval: 5000,
  })
}
