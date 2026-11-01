import type { ExplorerGalleryItem } from '@/lib/api'

export type ContentView = 'grid' | 'list'

export interface QuerySelection {
  token: string
  count: number
  excluded: Set<number>
}

export function galleryName(item: ExplorerGalleryItem): string {
  return item.title || item.title_jpn || item.source_id
}

/** Format a media duration in seconds as m:ss or h:mm:ss. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`
}
