'use client'

import useSWR, { useSWRConfig } from 'swr'
import useSWRMutation from 'swr/mutation'
import { api } from '@/lib/api'

export function useImportProgress(galleryId: number | null) {
  return useSWR(
    galleryId ? ['import/progress', galleryId] : null,
    () => api.import_.progress(galleryId!),
    { refreshInterval: 2000 },
  )
}

export function useBatchScan() {
  return useSWRMutation(
    'import/batch/scan',
    (_key: unknown, { arg }: { arg: { rootDir: string; pattern: string } }) =>
      api.import_.batchScan(arg.rootDir, arg.pattern),
  )
}

export function useBatchStart() {
  return useSWRMutation(
    'import/batch/start',
    (
      _key: unknown,
      {
        arg,
      }: {
        arg: {
          rootDir: string
          mode: string
          galleries: Array<{ path: string; artist: string | null; title: string }>
        }
      },
    ) => api.import_.batchStart(arg.rootDir, arg.mode, arg.galleries),
  )
}

export function useBatchProgress(batchId: string | null) {
  return useSWR(
    batchId ? ['import/batch/progress', batchId] : null,
    () => api.import_.batchProgress(batchId!),
    { refreshInterval: 2000 },
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

export function useAddLibrary() {
  return useSWRMutation(
    'import/addLibrary',
    (_key: unknown, { arg }: { arg: { path: string; label?: string } }) =>
      api.import_.addLibrary(arg.path, arg.label),
  )
}

export function useRemoveLibrary() {
  return useSWRMutation('import/removeLibrary', (_key: unknown, { arg }: { arg: number }) =>
    api.import_.removeLibrary(arg),
  )
}

export function useCancelRescan() {
  return useSWRMutation('import/rescan/cancel', () => api.import_.rescanCancel())
}

export function useBrowseFs(path: string, options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true
  return useSWR(enabled ? ['import/browse-fs', path] : null, () => api.import_.browseFs(path))
}

export function useMountPoints() {
  return useSWR('import/mount-points', () => api.import_.mountPoints())
}

export function useToggleMonitor() {
  const { mutate } = useSWRConfig()
  return useSWRMutation(
    'import/monitor/toggle',
    async (_key: unknown, { arg }: { arg: boolean }) => {
      const res = await api.import_.toggleMonitor(arg)
      mutate('import/monitor/status')
      return res
    },
  )
}

export function useRecentImports() {
  return useSWR('import/recent', () => api.import_.recent())
}

export function useScanSettings(enabled = true) {
  return useSWR(enabled ? 'import/scan-settings' : null, () => api.import_.getScanSettings())
}

export function useUpdateScanSettings() {
  const { mutate } = useSWRConfig()
  return useSWRMutation(
    'import/scan-settings/update',
    async (_key: unknown, { arg }: { arg: { enabled?: boolean; interval_hours?: number } }) => {
      const res = await api.import_.updateScanSettings(arg)
      mutate('import/scan-settings')
      return res
    },
  )
}
