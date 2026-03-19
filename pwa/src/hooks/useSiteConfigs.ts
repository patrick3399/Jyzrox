import useSWR from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useSiteConfigs() {
  return useSWR('admin-sites', () => api.adminSites.list())
}

export function useProbe() {
  return useSWRMutation('admin-sites-probe', (_key: string, { arg }: { arg: string }) =>
    api.adminSites.probe(arg),
  )
}

export function useUpdateSiteConfig() {
  return useSWRMutation(
    'admin-sites',
    (
      _key: string,
      { arg }: { arg: { sourceId: string; data: { download?: Record<string, unknown> } } },
    ) => api.adminSites.update(arg.sourceId, arg.data),
  )
}

export function useUpdateFieldMapping() {
  return useSWRMutation(
    'admin-sites',
    (
      _key: string,
      { arg }: { arg: { sourceId: string; fieldMapping: Record<string, string | null> } },
    ) => api.adminSites.updateFieldMapping(arg.sourceId, arg.fieldMapping),
  )
}

export function useResetSiteField() {
  return useSWRMutation(
    'admin-sites',
    (_key: string, { arg }: { arg: { sourceId: string; fieldPath: string } }) =>
      api.adminSites.reset(arg.sourceId, arg.fieldPath),
  )
}

export function useResetAdaptive() {
  return useSWRMutation('admin-sites', (_key: string, { arg }: { arg: string }) =>
    api.adminSites.resetAdaptive(arg),
  )
}
