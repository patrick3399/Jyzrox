import { t } from '@/lib/i18n'
import type { Gallery } from '@/lib/types'
import { sourceColorClass, sourceDisplayName } from '@/lib/sourceStyle'

/** Badge label and colour of a library gallery's site (local imports get a translated label). */
export function getSourceStyle(gallery: Pick<Gallery, 'source' | 'import_mode'>) {
  const label = gallery.source === 'local' ? t('library.local') : sourceDisplayName(gallery.source)
  return { label, className: sourceColorClass(gallery.source) }
}

/**
 * Action the detail page offers next to the download-status badge.
 *
 * `kind` is what the gallery is; `canEnqueue` is what we can do about it. They
 * are separate because a gallery can need attention we cannot act on — see
 * below.
 */
export type GalleryStatusAction = {
  kind: 'none' | 'outdated' | 'repair'
  canEnqueue: boolean
}

/**
 * Decide which status action a gallery should offer.
 *
 * `partial` means the last run left content behind — failed pages or failed
 * imports — so it always gets a repair action, independent of whether a
 * metadata check happened to report a page diff. Gating the action on
 * `pagesOutdated && complete` (the original condition) excluded precisely the
 * status that needs it, leaving partial galleries with no clickable affordance.
 *
 * A missing `source_url` suppresses only the button, never the badge. The
 * outdated signal comes from `checkUpdate(source, source_id)`, which never
 * consults `source_url`, so folding the two into one verdict silently hid the
 * warning on exactly the galleries that could not be repaired from the UI.
 *
 * Nothing is offered while a run is already in flight, since both actions
 * enqueue the same URL and would race the live job.
 */
export function galleryStatusAction(params: {
  downloadStatus: Gallery['download_status']
  hasSourceUrl: boolean
  pagesOutdated: boolean
}): GalleryStatusAction {
  const { downloadStatus, hasSourceUrl, pagesOutdated } = params
  if (downloadStatus === 'downloading') return { kind: 'none', canEnqueue: false }
  if (downloadStatus === 'partial') return { kind: 'repair', canEnqueue: hasSourceUrl }
  if (downloadStatus === 'complete' && pagesOutdated) {
    return { kind: 'outdated', canEnqueue: hasSourceUrl }
  }
  return { kind: 'none', canEnqueue: false }
}

export function getEventPosition(e: React.TouchEvent | React.MouseEvent): { x: number; y: number } {
  if ('touches' in e && e.touches.length > 0) {
    return { x: e.touches[0].clientX, y: e.touches[0].clientY }
  }
  if ('changedTouches' in e && e.changedTouches.length > 0) {
    return { x: e.changedTouches[0].clientX, y: e.changedTouches[0].clientY }
  }
  const me = e as React.MouseEvent
  return { x: me.clientX, y: me.clientY }
}
