'use client'

import { useEffect, useRef } from 'react'
import { api } from '@/lib/api'

interface SyncableGallery {
  source: string
  source_id: string
  import_mode?: string | null
}

/**
 * Reconciles a link-mode gallery with its source folder when it is opened.
 *
 * The backend compares one directory mtime, so this is cheap for an unchanged
 * folder. `onChanged` fires only when pages were added, removed, renamed or
 * replaced; a large change is handed to the worker instead, and the existing
 * `gallery.updated` WebSocket invalidation refreshes the page when it lands.
 */
export function useLinkGallerySync(
  gallery: SyncableGallery | null | undefined,
  onChanged: () => void,
) {
  const onChangedRef = useRef(onChanged)
  useEffect(() => {
    onChangedRef.current = onChanged
  })

  const source = gallery?.source ?? null
  const sourceId = gallery?.source_id ?? null
  const isLink = gallery?.import_mode === 'link'

  useEffect(() => {
    if (!source || !sourceId || !isLink) return
    let cancelled = false
    api.library
      .syncGallery(source, sourceId)
      .then((result) => {
        if (!cancelled && result.changed) onChangedRef.current()
      })
      .catch(() => {
        // Best-effort: the gallery still opens from what the DB already has.
      })
    return () => {
      cancelled = true
    }
  }, [source, sourceId, isLink])
}
