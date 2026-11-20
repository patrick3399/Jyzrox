/**
 * useUpdateGallery — the PATCH response must not wipe detail-only fields.
 *
 * PATCH /library/galleries/{source}/{id} serialises the bare row: it carries no
 * `media_stats` and a null `cover_thumb`. Writing that straight into the detail
 * cache made the size line vanish after a category edit, and SWR then discarded
 * the refetch that was already in flight, so it often never came back.
 *
 * Runs against real SWR so the cache write itself is what gets asserted.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import type { ReactNode } from 'react'
import type { Gallery } from '@/lib/types'

const { mockGetGallery, mockUpdateGallery } = vi.hoisted(() => ({
  mockGetGallery: vi.fn(),
  mockUpdateGallery: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  api: { library: { getGallery: mockGetGallery, updateGallery: mockUpdateGallery } },
}))
vi.mock('@/lib/ws', () => ({ useWsJobs: () => ({ lastJobUpdate: null }) }))

import { useLibraryGallery, useUpdateGallery } from '@/hooks/useLibraryGalleries'

const detail = {
  id: 7,
  source: 'local',
  source_id: '123',
  title: 'Gallery',
  category: 'Doujinshi',
  in_reading_list: false,
  cover_thumb: '/media/thumbs/ab/cover.webp',
  media_stats: { total_size: 1048576, image_count: 3, gif_count: 0, video_count: 0 },
} as unknown as Gallery

/** What PATCH actually returns: same row, no media_stats, cover_thumb null. */
function patchResponse(changes: Partial<Gallery>): Gallery {
  const { media_stats: _stats, ...rest } = detail
  return { ...rest, cover_thumb: null, ...changes } as Gallery
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>
  )
}

function renderDetail() {
  return renderHook(
    () => ({
      gallery: useLibraryGallery('local', '123'),
      update: useUpdateGallery('local', '123'),
    }),
    { wrapper },
  )
}

describe('useUpdateGallery cache merge', () => {
  beforeEach(() => {
    mockGetGallery.mockReset()
    mockUpdateGallery.mockReset()
    // First load resolves; any later refetch hangs, like one SWR would discard.
    mockGetGallery.mockResolvedValueOnce(detail).mockReturnValue(new Promise(() => {}))
  })

  it('category_edit_keeps_media_stats_and_cover_from_the_detail_fetch', async () => {
    mockUpdateGallery.mockResolvedValue(patchResponse({ category: 'Manga' }))
    const { result } = renderDetail()
    await waitFor(() => expect(result.current.gallery.data).toBeDefined())

    await act(async () => {
      await result.current.update.trigger({ category: 'Manga' })
    })

    expect(result.current.gallery.data?.category).toBe('Manga')
    expect(result.current.gallery.data?.media_stats?.total_size).toBe(1048576)
    expect(result.current.gallery.data?.cover_thumb).toBe('/media/thumbs/ab/cover.webp')
  })

  it('reading_list_toggle_through_the_hook_keeps_media_stats', async () => {
    mockUpdateGallery.mockResolvedValue(patchResponse({ in_reading_list: true }))
    const { result } = renderDetail()
    await waitFor(() => expect(result.current.gallery.data).toBeDefined())

    await act(async () => {
      await result.current.update.trigger({ in_reading_list: true })
    })

    expect(mockUpdateGallery).toHaveBeenCalledWith('local', '123', { in_reading_list: true })
    expect(result.current.gallery.data?.in_reading_list).toBe(true)
    expect(result.current.gallery.data?.media_stats?.total_size).toBe(1048576)
  })
})
