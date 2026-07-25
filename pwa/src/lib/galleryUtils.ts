import { t } from '@/lib/i18n'
import type { Gallery } from '@/lib/types'

// Full class strings listed explicitly so Tailwind detects them at build time.
// Spectrum order: red → orange → amber → yellow → lime → green → emerald → teal
//                 → cyan → sky → blue → indigo → violet → purple → fuchsia → pink → rose
const SOURCE_COLOR_PALETTE = [
  'bg-red-900/50 text-red-300 border-red-800',
  'bg-orange-900/50 text-orange-300 border-orange-800',
  'bg-amber-900/50 text-amber-300 border-amber-800',
  'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  'bg-lime-900/50 text-lime-300 border-lime-800',
  'bg-green-900/50 text-green-300 border-green-800',
  'bg-emerald-900/50 text-emerald-300 border-emerald-800',
  'bg-teal-900/50 text-teal-300 border-teal-800',
  'bg-cyan-900/50 text-cyan-300 border-cyan-800',
  'bg-sky-900/50 text-sky-300 border-sky-800',
  'bg-blue-900/50 text-blue-300 border-blue-800',
  'bg-indigo-900/50 text-indigo-300 border-indigo-800',
  'bg-violet-900/50 text-violet-300 border-violet-800',
  'bg-purple-900/50 text-purple-300 border-purple-800',
  'bg-fuchsia-900/50 text-fuchsia-300 border-fuchsia-800',
  'bg-pink-900/50 text-pink-300 border-pink-800',
  'bg-rose-900/50 text-rose-300 border-rose-800',
] as const

/** FNV-1a hash — better distribution than djb2 for short strings. */
function hashSourceColor(source: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < source.length; i++) {
    hash ^= source.charCodeAt(i)
    hash = (hash * 0x01000193) | 0
  }
  return Math.abs(hash)
}

/**
 * Returns the Tailwind class string for a given source key (e.g. "pixiv", "ehentai",
 * "local:link"). Uses FNV-1a hash to deterministically pick from SOURCE_COLOR_PALETTE.
 * Exported so consumers that only have a source string (e.g. artists page) can use it
 * without constructing a full Gallery object.
 */
function getSourceColorClass(source: string): string {
  return SOURCE_COLOR_PALETTE[hashSourceColor(source) % SOURCE_COLOR_PALETTE.length]
}

export function getSourceStyle(gallery: Pick<Gallery, 'source' | 'import_mode'>) {
  // Determine label
  let label: string
  if (gallery.source === 'ehentai') label = 'E-Hentai'
  else if (gallery.source === 'pixiv') label = 'Pixiv'
  else if (gallery.source === 'local') label = t('library.local')
  else label = gallery.source.charAt(0).toUpperCase() + gallery.source.slice(1)

  // Determine color — hash-based for all sources.
  const className = getSourceColorClass(gallery.source)

  return { label, className }
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
