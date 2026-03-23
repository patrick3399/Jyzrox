import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useSavedSearches() {
  return useSWR('saved-searches', () => api.savedSearches.list())
}

export function useRenameSavedSearch() {
  return useSWRMutation(
    'saved-searches',
    (_key: unknown, { arg }: { arg: { id: number; name: string } }) =>
      api.savedSearches.rename(arg.id, arg.name),
  )
}
