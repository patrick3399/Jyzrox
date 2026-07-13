/**
 * GalleryDlSection — Vitest suite
 *
 * Regression coverage for the gallery-dl upgrade failure-indication defense:
 *   - a failed upgrade event pushed over WebSocket renders a persistent
 *     failure status row (so the admin can't miss it) and fires an error toast
 *   - a successful event clears any failure row and refetches the version live
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import type { GdlUpgradeEvent } from '@/lib/types'

const h = vi.hoisted(() => ({
  lastGdlUpgrade: null as GdlUpgradeEvent | null,
}))

const mockGetVersion = vi.fn(async () => ({ current: '1.32.1', latest: '1.32.6' }))

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/api', () => ({
  api: { galleryDl: { getVersion: () => mockGetVersion(), upgrade: vi.fn(), rollback: vi.fn() } },
}))

vi.mock('@/lib/ws', () => ({
  useWsGdlUpgrade: () => ({ lastGdlUpgrade: h.lastGdlUpgrade }),
}))

import { GalleryDlSection } from '@/app/settings/workers/page'
import { toast } from 'sonner'

beforeEach(() => {
  h.lastGdlUpgrade = null
  vi.clearAllMocks()
})

describe('GalleryDlSection — upgrade failure indication', () => {
  it('test_failedUpgradeEvent_showsPersistentFailureRow_andErrorToast', async () => {
    const { rerender } = render(<GalleryDlSection />)
    await waitFor(() => expect(screen.getByText('1.32.1')).toBeInTheDocument())

    // A failed upgrade outcome arrives over the WebSocket.
    h.lastGdlUpgrade = {
      status: 'failed',
      old_version: '1.32.1',
      new_version: null,
      error: 'pip install failed: boom',
      rollback: false,
    }
    rerender(<GalleryDlSection />)

    await waitFor(() =>
      expect(screen.getByText(/galleryDlLastFailed.*boom/)).toBeInTheDocument(),
    )
    expect(toast.error).toHaveBeenCalledTimes(1)
  })

  it('test_rejectedUpgradeEvent_showsRejectedRow', async () => {
    const { rerender } = render(<GalleryDlSection />)
    await waitFor(() => expect(screen.getByText('1.32.1')).toBeInTheDocument())

    h.lastGdlUpgrade = {
      status: 'rejected',
      old_version: '1.32.1',
      new_version: null,
      error: '2 download(s) still running',
      rollback: false,
    }
    rerender(<GalleryDlSection />)

    await waitFor(() =>
      expect(screen.getByText(/galleryDlLastRejected.*still running/)).toBeInTheDocument(),
    )
  })

  it('test_successEvent_refetchesVersion_andShowsNoFailureRow', async () => {
    const { rerender } = render(<GalleryDlSection />)
    await waitFor(() => expect(screen.getByText('1.32.1')).toBeInTheDocument())
    expect(mockGetVersion).toHaveBeenCalledTimes(1) // initial mount fetch

    h.lastGdlUpgrade = {
      status: 'ok',
      old_version: '1.32.1',
      new_version: '1.32.6',
      error: null,
      rollback: false,
    }
    rerender(<GalleryDlSection />)

    // Success drives a live refetch instead of a blind timer.
    await waitFor(() => expect(mockGetVersion).toHaveBeenCalledTimes(2))
    expect(screen.queryByText(/galleryDlLastFailed/)).not.toBeInTheDocument()
    expect(toast.success).toHaveBeenCalledTimes(1)
  })
})
