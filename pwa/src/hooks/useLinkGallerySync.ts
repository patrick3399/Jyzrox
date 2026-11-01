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
 * folder. `onChanged` fires when pages were added, removed, renamed or
 * replaced, or when pages are still waiting for their hash (the sync registers
 * them without hashing; the worker fills them in in the background, and the
 * `gallery.updated` WebSocket event refreshes the page when that lands).
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
        // `pending` is the number of pages the sync left unhashed: they were
        // registered by this sync (or an earlier one), so the grid must refetch.
        if (!cancelled && (result.changed || (result.pending ?? 0) > 0)) onChangedRef.current()
      })
      .catch(() => {
        // Best-effort: the gallery still opens from what the DB already has.
      })
    return () => {
      cancelled = true
    }
  }, [source, sourceId, isLink])
}
