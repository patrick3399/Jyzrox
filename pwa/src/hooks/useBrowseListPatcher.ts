'use client'

import { useCallback } from 'react'
import { useProfile } from '@/hooks/useProfile'
import { publishBrowseListPatch } from '@/lib/browse/listPatches'
import type { BrowseListPatch } from '@/lib/browse/patch'
import { peekBrowseTabId } from '@/lib/browse/tabScope'

type BrowseListPatcherOptions = {
  sourceId: string
  schemaVersion: number
  validateItem?: (value: unknown) => boolean
}

/**
 * Publish a change made outside a browse list (a detail page) to the saved
 * lists of that source in this tab, so the list the user goes back to shows it
 * without a refetch. A no-op until the profile is known, or when this tab
 * never saved a list.
 */
export function useBrowseListPatcher<Item>({
  sourceId,
  schemaVersion,
  validateItem,
}: BrowseListPatcherOptions) {
  const { data: profile } = useProfile()
  const userId = profile?.username
  return useCallback(
    (patch: BrowseListPatch<Item>): void => {
      if (!userId) return
      let storage: Storage
      try {
        storage = window.sessionStorage
      } catch {
        return
      }
      const tabId = peekBrowseTabId(storage)
      if (!tabId) return
      publishBrowseListPatch({
        storage,
        scope: { userId, tabId, sourceId, schemaVersion },
        patch,
        validateItem,
      })
    },
    [schemaVersion, sourceId, userId, validateItem],
  )
}
