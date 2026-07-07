import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

// A note path with a space and CJK — every segment is percent-encoded in the URL.
const DECODED = ['挪德卡萊 - 最後的月之容器', 'Setting', '參考-菈烏瑪.md']
// Next's useParams() returns catch-all segments still percent-encoded (as they
// appear in the URL); the page must decode them before hitting the API.
const ENCODED_SEGMENTS = DECODED.map(encodeURIComponent)

vi.mock('next/navigation', () => ({
  useParams: () => ({ path: ENCODED_SEGMENTS }),
}))

// SWR mock that actually invokes the fetcher with its key, so we can assert
// what path the API client is called with.
vi.mock('swr', () => ({
  default: (key: unknown, fetcher: (k: unknown) => unknown) => {
    if (key && fetcher) fetcher(key)
    return { data: undefined, isLoading: true }
  },
}))

const readFile = vi.fn()
const appearances = vi.fn()
vi.mock('@/lib/api', () => ({
  api: { novels: { readFile: (...a: unknown[]) => readFile(...a), appearances: (...a: unknown[]) => appearances(...a) } },
}))

import NovelNotePage from '@/app/novels/note/[...path]/page'

describe('NovelNotePage', () => {
  beforeEach(() => {
    readFile.mockClear()
    appearances.mockClear()
  })

  it('decodes url-encoded route segments before fetching the note file', () => {
    render(<NovelNotePage />)
    expect(readFile).toHaveBeenCalledWith(DECODED.join('/'))
    expect(appearances).toHaveBeenCalledWith(DECODED.join('/'))
  })
})
