import { Suspense } from 'react'
import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PixivReaderPage from '@/app/reader/pixiv/[id]/page'

/**
 * The Pixiv reader is opened from the artwork page. Reader exits fall back to
 * `/library` unless told otherwise, so a reader with nothing to history-back to
 * (shared link, PWA relaunch) must be given the artwork route to land on.
 */

const h = vi.hoisted(() => ({
  replace: vi.fn(),
  swr: { data: undefined as unknown, error: undefined as unknown },
  readerProps: [] as Array<Record<string, unknown>>,
  fallbackProps: [] as Array<Record<string, unknown>>,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: h.replace }),
  useSearchParams: () => new URLSearchParams(''),
}))
vi.mock('swr', () => ({
  default: () => ({ data: h.swr.data, error: h.swr.error, isLoading: false, mutate: vi.fn() }),
}))
vi.mock('@/lib/api', () => ({
  api: { pixiv: { getIllustPages: vi.fn(), imageProxyUrl: (url: string) => url } },
}))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => undefined }))
vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('@/components/Reader', () => ({
  default: (props: Record<string, unknown>) => {
    h.readerProps.push(props)
    return <div data-testid="reader" />
  },
}))
vi.mock('@/components/Reader/ReaderFallbackScreen', () => ({
  ReaderFallbackScreen: (props: Record<string, unknown> & { children?: React.ReactNode }) => {
    h.fallbackProps.push(props)
    return <div data-testid="fallback">{props.children}</div>
  },
}))

async function renderPage(id: string) {
  await act(async () => {
    render(
      <Suspense>
        <PixivReaderPage params={Promise.resolve({ id })} />
      </Suspense>,
    )
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  h.swr.data = undefined
  h.swr.error = undefined
  h.readerProps.length = 0
  h.fallbackProps.length = 0
})

describe('Pixiv reader page — where its exits lead', () => {
  it('hands the artwork route to Reader so its exits do not fall back to the library', async () => {
    h.swr.data = { pages: [{ page_num: 1, url: 'https://i.pximg.net/a.jpg' }], page_count: 1 }

    await renderPage('118801677')

    expect(screen.getByTestId('reader')).toBeInTheDocument()
    expect(h.readerProps.at(-1)?.backHref).toBe('/pixiv/illust/118801677')
  })

  it('gives the loading screen the artwork route', async () => {
    await renderPage('118801677')

    expect(h.fallbackProps.at(-1)?.backHref).toBe('/pixiv/illust/118801677')
  })

  it('gives the error screen the artwork route', async () => {
    h.swr.error = new Error('boom')

    await renderPage('118801677')

    expect(h.fallbackProps.at(-1)?.backHref).toBe('/pixiv/illust/118801677')
  })

  it('falls back to the Pixiv section when the id is not a number', async () => {
    await renderPage('nope')

    expect(h.fallbackProps.at(-1)?.backHref).toBe('/pixiv')
  })

  it('sends an author-collection id to the gallery reader with replace, and exits to the artist', async () => {
    await renderPage('user:13419413')

    expect(h.replace).toHaveBeenCalledWith('/reader/gallery/pixiv/user%3A13419413')
    expect(h.fallbackProps.at(-1)?.backHref).toBe('/pixiv/user/13419413')
  })
})
