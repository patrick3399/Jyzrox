import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useSubscriptionGroups() {
  return useSWR('subscription-groups', () => api.subscriptionGroups.list())
}

export function useCreateGroup() {
  return useSWRMutation(
    'subscription-groups',
    (
      _key: string,
      {
        arg,
      }: { arg: { name: string; schedule?: string; concurrency?: number; priority?: number } },
    ) => api.subscriptionGroups.create(arg),
  )
}

export function useUpdateGroup() {
  return useSWRMutation(
    'subscription-groups',
    (
      _key: string,
      {
        arg,
      }: {
        arg: {
          id: number
          data: {
            name?: string
            schedule?: string
            concurrency?: number
            priority?: number
            enabled?: boolean
          }
        }
      },
    ) => api.subscriptionGroups.update(arg.id, arg.data),
  )
}

export function useDeleteGroup() {
  return useSWRMutation('subscription-groups', (_key: string, { arg }: { arg: number }) =>
    api.subscriptionGroups.delete(arg),
  )
}

export function useRunGroup() {
  return useSWRMutation('subscription-groups', (_key: string, { arg }: { arg: number }) =>
    api.subscriptionGroups.run(arg),
  )
}

export function usePauseGroup() {
  return useSWRMutation('subscription-groups', (_key: string, { arg }: { arg: number }) =>
    api.subscriptionGroups.pause(arg),
  )
}

export function useResumeGroup() {
  return useSWRMutation('subscription-groups', (_key: string, { arg }: { arg: number }) =>
    api.subscriptionGroups.resume(arg),
  )
}

export function useBulkMove() {
  return useSWRMutation(
    'subscriptions',
    (_key: string, { arg }: { arg: { sub_ids: number[]; group_id: number | null } }) =>
      api.subscriptionGroups.bulkMove(arg.sub_ids, arg.group_id),
  )
}
