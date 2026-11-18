/** The gallery an earlier download left for this account (409 `{code: "gallery_exists"}`). */
export interface ExistingGalleryHint {
  source: string
  sourceId: string
  title: string
  pages: number
}

/**
 * Read the "this account was already downloaded" refusal out of an error thrown
 * by the API client. Anything else (a plain Error, `subscription_exists`) is not a hint.
 */
export function existingGalleryHint(err: unknown): ExistingGalleryHint | null {
  if (typeof err !== 'object' || err === null) return null
  const detail = (err as { detail?: unknown }).detail
  if (typeof detail !== 'object' || detail === null) return null
  const body = detail as {
    code?: unknown
    source?: unknown
    source_id?: unknown
    title?: unknown
    pages?: unknown
  }
  if (body.code !== 'gallery_exists') return null
  if (typeof body.source !== 'string' || typeof body.source_id !== 'string') return null
  return {
    source: body.source,
    sourceId: body.source_id,
    title: typeof body.title === 'string' && body.title ? body.title : body.source_id,
    pages: typeof body.pages === 'number' ? body.pages : 0,
  }
}
