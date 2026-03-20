/**
 * useIllustActions — Vitest test suite
 *
 * Covers:
 *   Initial state — bookmarked matches illust.is_bookmarked
 *   Initial state — downloading is false
 *   Initial state — bookmarking is false
 *   handleDownload — calls api.download.enqueue with the correct artwork URL
 *   handleDownload — sets downloading to true during the call, false after
 *   handleDownload — shows toast.success('browse.addedToQueue') on success
 *   handleDownload — shows toast.error with the error message on failure
 *   handleDownload — guards against double-submit (no-op when already downloading)
 *   handleBookmark (add) — calls api.pixiv.addBookmark and sets bookmarked to true
 *   handleBookmark (add) — shows toast.error on failure
 *   handleBookmark (remove) — calls api.pixiv.deleteBookmark and sets bookmarked to false
 *   handleBookmark guard — does nothing when bookmarking is already true
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations, so any variables
 *   referenced inside a factory must be declared with vi.hoisted() to guarantee
 *   they exist at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { PixivIllust } from '@/lib/types'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockEnqueue, mockAddBookmark, mockDeleteBookmark, mockToastSuccess, mockToastError } =
  vi.hoisted(() => ({
    mockEnqueue: vi.fn(),
    mockAddBookmark: vi.fn(),
    mockDeleteBookmark: vi.fn(),
    mockToastSuccess: vi.fn(),
    mockToastError: vi.fn(),
  }))

// ── Module mocks ──────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    download: {
      enqueue: mockEnqueue,
    },
    pixiv: {
      addBookmark: mockAddBookmark,
      deleteBookmark: mockDeleteBookmark,
    },
  },
}))

vi.mock('sonner', () => ({
  toast: {
    success: mockToastSuccess,
    error: mockToastError,
  },
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useIllustActions } from '@/hooks/useIllustActions'

// ── Helpers ───────────────────────────────────────────────────────────

function makeIllust(overrides: Partial<PixivIllust> = {}): PixivIllust {
  return {
    id: 12345,
    title: 'Test Illust',
    type: 'illust',
    image_urls: { square_medium: '', medium: '', large: '' },
    caption: '',
    user: { id: 1, name: 'Artist', account: 'artist', profile_image: '' },
    tags: [],
    create_date: '2024-01-01T00:00:00',
    page_count: 1,
    width: 800,
    height: 600,
    sanity_level: 2,
    total_view: 100,
    total_bookmarks: 10,
    is_bookmarked: false,
    ...overrides,
  }
}

function makeMockEvent() {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
  } as unknown as React.MouseEvent
}

// ── Shared setup ──────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockEnqueue.mockResolvedValue(undefined)
  mockAddBookmark.mockResolvedValue(undefined)
  mockDeleteBookmark.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.clearAllMocks()
})

// ── Tests ─────────────────────────────────────────────────────────────

describe('useIllustActions — initial state', () => {
  it('test_useIllustActions_initialState_bookmarkedMatchesIllust_whenNotBookmarked', () => {
    const illust = makeIllust({ is_bookmarked: false })
    const { result } = renderHook(() => useIllustActions(illust))

    expect(result.current.bookmarked).toBe(false)
  })

  it('test_useIllustActions_initialState_bookmarkedMatchesIllust_whenBookmarked', () => {
    const illust = makeIllust({ is_bookmarked: true })
    const { result } = renderHook(() => useIllustActions(illust))

    expect(result.current.bookmarked).toBe(true)
  })

  it('test_useIllustActions_initialState_downloadingIsFalse', () => {
    const illust = makeIllust()
    const { result } = renderHook(() => useIllustActions(illust))

    expect(result.current.downloading).toBe(false)
  })

  it('test_useIllustActions_initialState_bookmarkingIsFalse', () => {
    const illust = makeIllust()
    const { result } = renderHook(() => useIllustActions(illust))

    expect(result.current.bookmarking).toBe(false)
  })
})

describe('useIllustActions — handleDownload()', () => {
  it('test_useIllustActions_handleDownload_callsEnqueueWithCorrectUrl', async () => {
    const illust = makeIllust({ id: 99999 })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleDownload(event)
    })

    expect(mockEnqueue).toHaveBeenCalledOnce()
    expect(mockEnqueue).toHaveBeenCalledWith('https://www.pixiv.net/artworks/99999')
  })

  it('test_useIllustActions_handleDownload_callsPreventDefaultAndStopPropagation', async () => {
    const illust = makeIllust()
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleDownload(event)
    })

    expect(event.preventDefault).toHaveBeenCalledOnce()
    expect(event.stopPropagation).toHaveBeenCalledOnce()
  })

  it('test_useIllustActions_handleDownload_setsDownloadingTrueWhileRunning_thenFalseAfter', async () => {
    const illust = makeIllust()
    let resolveEnqueue!: () => void
    mockEnqueue.mockReturnValue(
      new Promise<void>((res) => {
        resolveEnqueue = res
      }),
    )

    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    // Start the download without awaiting
    let downloadPromise: Promise<void>
    act(() => {
      downloadPromise = result.current.handleDownload(event)
    })

    // downloading should be true while the promise is pending
    expect(result.current.downloading).toBe(true)

    // Resolve the enqueue and wait for the hook to finish
    await act(async () => {
      resolveEnqueue()
      await downloadPromise
    })

    expect(result.current.downloading).toBe(false)
  })

  it('test_useIllustActions_handleDownload_showsToastSuccessOnSuccess', async () => {
    const illust = makeIllust()
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleDownload(event)
    })

    expect(mockToastSuccess).toHaveBeenCalledOnce()
    expect(mockToastSuccess).toHaveBeenCalledWith('browse.addedToQueue')
  })

  it('test_useIllustActions_handleDownload_showsToastErrorWithMessage_onFailure', async () => {
    mockEnqueue.mockRejectedValue(new Error('Network timeout'))
    const illust = makeIllust()
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleDownload(event)
    })

    expect(mockToastError).toHaveBeenCalledOnce()
    expect(mockToastError).toHaveBeenCalledWith('Network timeout')
    expect(mockToastSuccess).not.toHaveBeenCalled()
  })

  it('test_useIllustActions_handleDownload_showsToastErrorWithFallback_onNonErrorThrow', async () => {
    mockEnqueue.mockRejectedValue('plain string error')
    const illust = makeIllust()
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleDownload(event)
    })

    expect(mockToastError).toHaveBeenCalledOnce()
    expect(mockToastError).toHaveBeenCalledWith('common.failedToSave')
  })

  it('test_useIllustActions_handleDownload_secondCallWhileDownloading_isNoOp', async () => {
    const illust = makeIllust()
    let resolveEnqueue!: () => void
    mockEnqueue.mockReturnValue(
      new Promise<void>((res) => {
        resolveEnqueue = res
      }),
    )

    const { result } = renderHook(() => useIllustActions(illust))
    const event1 = makeMockEvent()
    const event2 = makeMockEvent()

    // Start first download
    let firstPromise: Promise<void>
    act(() => {
      firstPromise = result.current.handleDownload(event1)
    })

    // While downloading is true, call handleDownload again — should be a no-op
    await act(async () => {
      await result.current.handleDownload(event2)
    })

    // Resolve the first enqueue
    await act(async () => {
      resolveEnqueue()
      await firstPromise
    })

    // enqueue was only called once despite two handleDownload calls
    expect(mockEnqueue).toHaveBeenCalledOnce()
  })
})

describe('useIllustActions — handleBookmark() add', () => {
  it('test_useIllustActions_handleBookmark_add_callsAddBookmarkWithId', async () => {
    const illust = makeIllust({ is_bookmarked: false, id: 12345 })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleBookmark(event)
    })

    expect(mockAddBookmark).toHaveBeenCalledOnce()
    expect(mockAddBookmark).toHaveBeenCalledWith(12345)
    expect(mockDeleteBookmark).not.toHaveBeenCalled()
  })

  it('test_useIllustActions_handleBookmark_add_setsBookmarkedToTrue', async () => {
    const illust = makeIllust({ is_bookmarked: false })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleBookmark(event)
    })

    expect(result.current.bookmarked).toBe(true)
  })

  it('test_useIllustActions_handleBookmark_add_showsToastErrorOnFailure', async () => {
    mockAddBookmark.mockRejectedValue(new Error('Bookmark failed'))
    const illust = makeIllust({ is_bookmarked: false })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleBookmark(event)
    })

    expect(mockToastError).toHaveBeenCalledOnce()
    expect(mockToastError).toHaveBeenCalledWith('Bookmark failed')
    // bookmarked should remain unchanged on failure
    expect(result.current.bookmarked).toBe(false)
  })
})

describe('useIllustActions — handleBookmark() remove', () => {
  it('test_useIllustActions_handleBookmark_remove_callsDeleteBookmarkWithId', async () => {
    const illust = makeIllust({ is_bookmarked: true, id: 12345 })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleBookmark(event)
    })

    expect(mockDeleteBookmark).toHaveBeenCalledOnce()
    expect(mockDeleteBookmark).toHaveBeenCalledWith(12345)
    expect(mockAddBookmark).not.toHaveBeenCalled()
  })

  it('test_useIllustActions_handleBookmark_remove_setsBookmarkedToFalse', async () => {
    const illust = makeIllust({ is_bookmarked: true })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleBookmark(event)
    })

    expect(result.current.bookmarked).toBe(false)
  })
})

describe('useIllustActions — handleBookmark() guard', () => {
  it('test_useIllustActions_handleBookmark_guard_doesNothingWhenAlreadyBookmarking', async () => {
    const illust = makeIllust({ is_bookmarked: false })
    let resolveBookmark!: () => void
    mockAddBookmark.mockReturnValue(
      new Promise<void>((res) => {
        resolveBookmark = res
      }),
    )

    const { result } = renderHook(() => useIllustActions(illust))
    const event1 = makeMockEvent()
    const event2 = makeMockEvent()

    // Start first bookmark action
    let firstPromise: Promise<void>
    act(() => {
      firstPromise = result.current.handleBookmark(event1)
    })

    // While bookmarking is true, call handleBookmark again — should be a no-op
    await act(async () => {
      await result.current.handleBookmark(event2)
    })

    // Resolve the first bookmark
    await act(async () => {
      resolveBookmark()
      await firstPromise
    })

    // addBookmark was only called once despite two handleBookmark calls
    expect(mockAddBookmark).toHaveBeenCalledOnce()
  })

  it('test_useIllustActions_handleBookmark_guard_bookmarkingResetToFalseAfterCompletion', async () => {
    const illust = makeIllust({ is_bookmarked: false })
    const { result } = renderHook(() => useIllustActions(illust))
    const event = makeMockEvent()

    await act(async () => {
      await result.current.handleBookmark(event)
    })

    expect(result.current.bookmarking).toBe(false)
  })
})
