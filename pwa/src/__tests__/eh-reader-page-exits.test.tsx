/**
 * Regression (audit EH-reader exits): the E-Hentai proxy reader route handed
 * `Reader` and `ReaderFallbackScreen` no back target, and its inline "Go back"
 * buttons called a bare `router.back()`.
 *
 * With `window.history.length === 1` (a shared link, a new tab, a PWA relaunch
 * onto the reader URL) `router.back()` does nothing, and reader routes have no
 * chrome and no swipe-back, so the user was trapped. Every exit must resolve
 * through `smartBack` to the gallery detail page the reader was opened from.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

const router = vi.hoisted(() => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }))
const galleryState = vi.hoisted(() => ({
  data: undefined as unknown,
  error: undefined as Error | undefined,
  isLoading: false,
}))
const tokenState = vi.hoisted(() => ({
  tokenMap: {} as Record<number, string>,
  error: undefined as Error | undefined,
}))
const readerProps = vi.hoisted(() => ({ current: undefined as Record<string, unknown> | undefined }))
const params = vi.hoisted(() => ({ gid: '123', token: 'abc' }))

vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useParams: () => params,
  useSearchParams: () => new URLSearchParams('page=2'),
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => galleryState,
  useEhGalleryImagesPaginated: () => ({
    tokenMap: tokenState.tokenMap,
    previewMap: {},
    isLoading: false,
    error: tokenState.error,
    onPageChange: vi.fn(),
    fetchUpTo: vi.fn(),
  }),
}))
vi.mock('@/components/Reader', () => ({
  default: (props: Record<string, unknown>) => {
    readerProps.current = props
    return <div data-testid="reader" />
  },
}))
vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <div data-testid="spinner" />,
}))

import EhProxyReaderPage from '@/app/e-hentai/read/[gid]/[token]/page'

const DETAIL_HREF = '/e-hentai/123/abc'

function setHistoryLength(length: number) {
  Object.defineProperty(window.history, 'length', { configurable: true, value: length })
}

beforeEach(() => {
  vi.clearAllMocks()
  readerProps.current = undefined
  galleryState.data = undefined
  galleryState.error = undefined
  galleryState.isLoading = false
  tokenState.tokenMap = {}
  tokenState.error = undefined
  params.gid = '123'
  params.token = 'abc'
  setHistoryLength(1)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('E-Hentai proxy reader exits', () => {
  it('passes the gallery detail page to Reader as its back target', () => {
    galleryState.data = { gid: 123, token: 'abc', pages: 10 }
    tokenState.tokenMap = { 1: 'tok' }

    render(<EhProxyReaderPage />)

    expect(screen.getByTestId('reader')).toBeInTheDocument()
    expect(readerProps.current?.backHref).toBe(DETAIL_HREF)
  })

  it('error state: the inline Go back pushes the detail page when history has nothing to go back to', () => {
    galleryState.error = new Error('boom')

    render(<EhProxyReaderPage />)
    fireEvent.click(screen.getByRole('button', { name: 'common.goBack' }))

    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledWith(DETAIL_HREF)
  })

  it('error state: the fallback screen close control resolves to the detail page too', () => {
    galleryState.error = new Error('boom')

    render(<EhProxyReaderPage />)
    fireEvent.click(screen.getByRole('button', { name: 'reader.goBack' }))

    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledWith(DETAIL_HREF)
  })

  it('invalid id: the fallback screen close control resolves to the E-Hentai list (no gallery page exists)', () => {
    params.gid = 'not-a-number'

    render(<EhProxyReaderPage />)
    fireEvent.click(screen.getByRole('button', { name: 'reader.goBack' }))

    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledWith('/e-hentai')
  })

  it('slow-loading state: the inline Go back pushes the detail page', () => {
    vi.useFakeTimers()
    galleryState.isLoading = true

    render(<EhProxyReaderPage />)
    act(() => {
      vi.advanceTimersByTime(8000)
    })
    fireEvent.click(screen.getByRole('button', { name: 'common.goBack' }))

    expect(router.back).not.toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledWith(DETAIL_HREF)
  })

  it('still steps back through history when there is somewhere to go', () => {
    setHistoryLength(3)
    galleryState.error = new Error('boom')

    render(<EhProxyReaderPage />)
    fireEvent.click(screen.getByRole('button', { name: 'common.goBack' }))

    expect(router.back).toHaveBeenCalledTimes(1)
    expect(router.push).not.toHaveBeenCalled()
  })
})
