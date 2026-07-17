import { apiFetch, qs } from './client'

// ── Import ────────────────────────────────────────────────────────────

export const import_ = {
  batchScan: (rootDir: string, pattern: string) =>
    apiFetch<{
      matches: Array<{
        rel_path: string
        abs_path: string
        artist: string | null
        title: string
        file_count: number
      }>
      unmatched: Array<{ rel_path: string; file_count: number }>
    }>('/api/import/batch/scan', {
      method: 'POST',
      body: JSON.stringify({ root_dir: rootDir, pattern }),
    }),

  batchStart: (
    rootDir: string,
    mode: string,
    galleries: Array<{ path: string; artist: string | null; title: string }>,
  ) =>
    apiFetch<{ batch_id: string; total: number }>('/api/import/batch/start', {
      method: 'POST',
      body: JSON.stringify({ root_dir: rootDir, mode, galleries }),
    }),

  batchProgress: (batchId: string) =>
    apiFetch<{
      total: number
      completed: number
      failed: number
      current_gallery_id: number | null
      status: string
      conflicts?: number
    }>(`/api/import/batch/progress/${batchId}`),

  conflictMode: () => apiFetch<{ mode: string }>('/api/import/conflict-mode'),
  setConflictMode: (mode: string) =>
    apiFetch<{ mode: string }>('/api/import/conflict-mode', {
      method: 'PATCH',
      body: JSON.stringify({ mode }),
    }),
  conflicts: (status = 'pending') =>
    apiFetch<{
      conflicts: Array<{
        id: number
        existing_gallery_id: number | null
        source: string
        source_id: string
        incoming: Record<string, unknown>
        status: string
        resolution: string | null
        created_at: string
      }>
    }>(`/api/import/conflicts${qs({ status })}`),
  resolveConflict: (id: number, resolution: 'merge' | 'skip') =>
    apiFetch<{ status: string; resolution: string }>(`/api/import/conflicts/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ resolution }),
    }),

  rescanLibraryPath: (libraryId: number) =>
    apiFetch<{ status: string }>(`/api/import/rescan/path/${libraryId}`, { method: 'POST' }),

  progress: (galleryId: number) =>
    apiFetch<{ gallery_id: number; processed: number; total: number; status: string }>(
      `/api/import/progress/${galleryId}`,
    ),

  rescan: () => apiFetch<{ status: string }>('/api/import/rescan', { method: 'POST' }),

  rescanGallery: (id: number) =>
    apiFetch<{ status: string; gallery_id: number }>(`/api/import/rescan/${id}`, {
      method: 'POST',
    }),

  rescanStatus: () =>
    apiFetch<{
      running: boolean
      processed?: number
      total?: number
      current_gallery?: string
      status?: string
    }>('/api/import/rescan/status'),

  rescanCancel: () => apiFetch<{ status: string }>('/api/import/rescan/cancel', { method: 'POST' }),

  libraries: () =>
    apiFetch<
      Array<{
        id: number | null
        path: string
        label: string
        enabled: boolean
        monitor: boolean
        pattern: string
        import_mode: string
        display_pattern: string
        gallery_count: number
        is_primary: boolean
        exists: boolean
        added_at: string | null
      }>
    >('/api/import/libraries'),

  addLibrary: (path: string, label?: string) =>
    apiFetch<{ status: string; path: string }>('/api/import/libraries', {
      method: 'POST',
      body: JSON.stringify({ path, label }),
    }),

  removeLibrary: (id: number) =>
    apiFetch<{ status: string }>(`/api/import/libraries/${id}`, { method: 'DELETE' }),

  monitorStatus: () =>
    apiFetch<{ enabled: boolean; running: boolean; watched_paths: string[] }>(
      '/api/import/monitor/status',
    ),

  toggleMonitor: (enabled: boolean) =>
    apiFetch<{ status: string }>('/api/import/monitor/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  browseFs: (path?: string) =>
    apiFetch<{ path: string; parent: string | null; entries: { name: string; type: string }[] }>(
      `/api/import/browse-fs${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    ),

  mountPoints: () =>
    apiFetch<{ mounts: { name: string; path: string; type: string }[] }>(
      '/api/import/mount-points',
    ),

  recent: (): Promise<
    Array<{ id: number; title: string; pages: number; status: string; added_at: string }>
  > => apiFetch('/api/import/recent'),

  getScanSettings: (): Promise<{
    enabled: boolean
    interval_hours: number
    last_run: string | null
  }> => apiFetch('/api/import/scan-settings'),

  updateScanSettings: (data: {
    enabled?: boolean
    interval_hours?: number
  }): Promise<{ enabled: boolean; interval_hours: number; last_run: string | null }> =>
    apiFetch('/api/import/scan-settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
}
