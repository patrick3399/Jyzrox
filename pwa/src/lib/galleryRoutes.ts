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
  return `/reader/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}${suffix}`
}
