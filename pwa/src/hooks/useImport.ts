'use client'

import useSWR, { useSWRConfig } from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useBrowseDirectory(path: string, library = '') {
  return useSWR(['import/browse', path, library], () => api.import_.browse(path, library))
}

export function useRecentImports() {
  return useSWR('import/recent', () => api.import_.recent(), {
    refreshInterval: 5000,
    dedupingInterval: 3000,
  })
}

export function useImportProgress(galleryId: number | null) {
  return useSWR(
    galleryId ? ['import/progress', galleryId] : null,
    () => api.import_.progress(galleryId!),
    { refreshInterval: 2000 },
  )
}

export function useStartImport() {
  return useSWRMutation(
    'import/start',
    (
      _key: unknown,
      { arg }: { arg: { sourceDir: string; title?: string } },
    ) => api.import_.start(arg.sourceDir, arg.title),
  )
}

export function useRescanLibraryPath() {
  return useSWRMutation('import/rescan/path', async (_key: string, { arg }: { arg: number }) => {
    return api.import_.rescanLibraryPath(arg)
  })
}

export function useRescanLibrary() {
  return useSWRMutation('import/rescan', () => api.import_.rescan())
}

export function useRescanStatus() {
  return useSWR('import/rescan/status', () => api.import_.rescanStatus(), {
    refreshInterval: 3000,
    dedupingInterval: 2000,
  })
}

export function useLibraries() {
  return useSWR('import/libraries', () => api.import_.libraries())
}

export function useMonitorStatus() {
  return useSWR('import/monitor/status', () => api.import_.monitorStatus(), {
    refreshInterval: 10000,
  })
}

export function useAutoDiscover() {
  return useSWRMutation('import/discover', () => api.import_.discover())
}

export function useAddLibrary() {
  return useSWRMutation(
    'import/addLibrary',
    (_key: unknown, { arg }: { arg: { path: string; label?: string } }) =>
      api.import_.addLibrary(arg.path, arg.label),
  )
}

export function useRemoveLibrary() {
  return useSWRMutation(
    'import/removeLibrary',
    (_key: unknown, { arg }: { arg: number }) => api.import_.removeLibrary(arg),
  )
}

export function useScanSettings() {
  return useSWR('import/scan-settings', () => api.import_.scanSettings())
}

export function useUpdateScanSettings() {
  return useSWRMutation(
    'import/scan-settings',
    (_key: unknown, { arg }: { arg: { enabled?: boolean; interval_hours?: number } }) =>
      api.import_.updateScanSettings(arg),
  )
}

export function useCancelRescan() {
  return useSWRMutation('import/rescan/cancel', () => api.import_.rescanCancel())
}

export function useBrowseFs(path: string, options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true
  return useSWR(
    enabled ? ['import/browse-fs', path] : null,
    () => api.import_.browseFs(path),
  )
}

export function useMountPoints() {
  return useSWR('import/mount-points', () => api.import_.mountPoints())
}

export function useToggleMonitor() {
  const { mutate } = useSWRConfig()
  return useSWRMutation('/api/import/monitor/status', async (_key: unknown, { arg }: { arg: boolean }) => {
    const res = await api.import_.toggleMonitor(arg)
    mutate('import/monitor/status')
    return res
  })
}
