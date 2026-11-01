/**
 * The share target's exit after queueing a download is the one call site
 * outside `lib/navBack.ts` allowed a bare `router.back()` (see the
 * `no-restricted-syntax` ban in `eslint.config.mjs`).
 *
 * A share-sheet launch usually opens the page with a one-entry history, where
 * `router.back()` is a no-op. There the page must close the window instead, so
 * the user lands back in the app they shared from. `smartBack` would push a
 * fallback route and leave Jyzrox open on top of that app.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ShareTargetPage from '@/app/share-target/page'

const router = vi.hoisted(() => ({
  back: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}))

const quickDownload = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams('url=https://www.pixiv.net/artworks/1'),
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }))

vi.mock('@/lib/api', () => ({
  api: { download: { quickDownload, enqueue: vi.fn() } },
}))

let historyLength = 1
let close: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  quickDownload.mockResolvedValue({ job_id: 'job-1' })
  // jsdom's close() tears the test window down; only record the call.
  close = vi.spyOn(window, 'close').mockImplementation(() => {})
  Object.defineProperty(window.history, 'length', {
    configurable: true,
    get: () => historyLength,
  })
})

afterEach(() => {
  close.mockRestore()
  delete (window.history as unknown as { length?: number }).length
})

describe('share target exit after queueing', () => {
  it('closes the window instead of a no-op router.back() on a one-entry history', async () => {
    historyLength = 1
    render(<ShareTargetPage />)

    fireEvent.click(screen.getByText('share.download'))

    await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('walks back to the page it was opened over when there is history', async () => {
    historyLength = 3
    render(<ShareTargetPage />)

    fireEvent.click(screen.getByText('share.download'))

    await waitFor(() => expect(router.back).toHaveBeenCalledTimes(1))
    expect(close).not.toHaveBeenCalled()
  })
})
