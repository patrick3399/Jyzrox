/**
 * useLinkGallerySync — syncs a link-mode gallery with its folder on open.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

const { mockSyncGallery } = vi.hoisted(() => ({ mockSyncGallery: vi.fn() }))

vi.mock('@/lib/api', () => ({
  api: { library: { syncGallery: mockSyncGallery } },
}))

import { useLinkGallerySync } from '@/hooks/useLinkGallerySync'

const linkGallery = { source: 'local', source_id: 'Cosplay/a/b', import_mode: 'link' }

describe('useLinkGallerySync', () => {
  beforeEach(() => {
    mockSyncGallery.mockReset()
  })

  it('calls onChanged when the folder gained or lost pages', async () => {
    mockSyncGallery.mockResolvedValue({ status: 'synced', changed: true })
    const onChanged = vi.fn()

    renderHook(() => useLinkGallerySync(linkGallery, onChanged))

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
    expect(mockSyncGallery).toHaveBeenCalledWith('local', 'Cosplay/a/b')
  })

  it('calls onChanged when the sync left pages pending even though nothing changed', async () => {
    mockSyncGallery.mockResolvedValue({ status: 'unchanged', changed: false, pending: 3 })
    const onChanged = vi.fn()

    renderHook(() => useLinkGallerySync(linkGallery, onChanged))

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
  })

  it('does not call onChanged when the folder is unchanged', async () => {
    mockSyncGallery.mockResolvedValue({ status: 'unchanged', changed: false, pending: 0 })
    const onChanged = vi.fn()

    renderHook(() => useLinkGallerySync(linkGallery, onChanged))

    await waitFor(() => expect(mockSyncGallery).toHaveBeenCalledTimes(1))
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('does not sync a gallery that is not link mode', () => {
    renderHook(() =>
      useLinkGallerySync({ source: 'ehentai', source_id: '1', import_mode: null }, vi.fn()),
    )

    expect(mockSyncGallery).not.toHaveBeenCalled()
  })

  it('does not sync before the gallery has loaded', () => {
    renderHook(() => useLinkGallerySync(undefined, vi.fn()))

    expect(mockSyncGallery).not.toHaveBeenCalled()
  })

  it('swallows a failed sync so the gallery still opens from the DB', async () => {
    mockSyncGallery.mockRejectedValue(new Error('boom'))
    const onChanged = vi.fn()

    renderHook(() => useLinkGallerySync(linkGallery, onChanged))

    await waitFor(() => expect(mockSyncGallery).toHaveBeenCalledTimes(1))
    expect(onChanged).not.toHaveBeenCalled()
  })
})
