export type SwrOpts = { signal?: AbortSignal }

/**
 * Job states after which a library list may be stale. `cancelled` and `failed`
 * matter as much as `done`/`partial`: the worker rolls back the gallery a run
 * created, so a list that keeps showing it leaves a "downloading" card behind.
 */
const GALLERY_CHANGING_JOB_STATUSES: ReadonlySet<string> = new Set([
  'done',
  'partial',
  'cancelled',
  'failed',
])

export function isGalleryChangingJobStatus(status: string): boolean {
  return GALLERY_CHANGING_JOB_STATUSES.has(status)
}
