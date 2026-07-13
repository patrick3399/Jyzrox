export function decodeRouteSegment(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export function galleryHref(source: string, sourceId: string): string {
  return `/library/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`
}

export function readerHref(source: string, sourceId: string, page?: number): string {
  const suffix = page ? `?page=${page}` : ''
  // `/reader/pixiv/[id]` is the remote-artwork reader and only accepts a
  // numeric illust ID. Author collections use an opaque `user:<id>` ID.
  if (source === 'pixiv' && sourceId.startsWith('user:')) {
    return `/reader/gallery/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}${suffix}`
  }
  return `/reader/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}${suffix}`
}
