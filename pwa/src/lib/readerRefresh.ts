import type { Gallery, GalleryImage } from '@/lib/types'

export const READER_DOWNLOAD_REFRESH_INTERVAL_MS = 4000

export function readerImagesEqual(current: GalleryImage[], next: GalleryImage[]): boolean {
  if (current.length !== next.length) return false
  return current.every((image, index) => {
    const candidate = next[index]
    return (
      candidate != null &&
      image.id === candidate.id &&
      image.page_num === candidate.page_num &&
      image.file_path === candidate.file_path &&
      image.thumb_path === candidate.thumb_path &&
      image.media_type === candidate.media_type &&
      image.visibility === candidate.visibility
    )
  })
}

export function readerGalleryStateEqual(current: Gallery, next: Gallery): boolean {
  return (
    current.id === next.id &&
    current.download_status === next.download_status &&
    current.pages === next.pages &&
    current.title === next.title &&
    current.cover_thumb === next.cover_thumb
  )
}

export function numberSetsEqual(current: number[], next: number[]): boolean {
  if (current.length !== next.length) return false
  const currentSet = new Set(current)
  return next.every((value) => currentSet.has(value))
}
