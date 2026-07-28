/**
 * Regression test: E-Hentai browse thumbnails must load lazily.
 *
 * Bug: ListCard/GridCard rendered their thumbnail through <AppImage> without a
 * `loading` prop, so every tile fetched eagerly on mount. With `limit: 50` per
 * page (app/e-hentai/page.tsx), one loadMore() fired 50 concurrent
 * /api/eh/thumb-proxy requests — nginx logs showed 50-request bursts every ~2s,
 * roughly 1500/min against a 120/min per-user budget, so scrolling past the
 * third page turned every thumbnail into a 429.
 *
 * Asserting on `loading="lazy"` pins the exact condition: offscreen tiles must
 * not issue a request until they approach the viewport.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GridCard, ListCard } from '@/components/eh/EhBrowseCards'
import type { EhGallery } from '@/lib/types'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
  usePathname: () => '/e-hentai',
  useSearchParams: () => new URLSearchParams(''),
}))

const gallery = {
  gid: 12345,
  token: 'abcdef',
  title: 'Test Gallery',
  title_jpn: '',
  category: 'Doujinshi',
  pages: 30,
  rating: 4.5,
  tags: ['language:english'],
  thumb: 'https://ehgt.org/thumb/001.jpg',
  uploader: 'tester',
  posted: 1700000000,
  filesize: 1024,
  expunged: false,
} as unknown as EhGallery

describe('E-Hentai browse thumbnails', () => {
  it('marks the grid card thumbnail lazy so offscreen tiles issue no request', () => {
    render(<GridCard gallery={gallery} onClick={vi.fn()} onUploaderClick={vi.fn()} />)

    const img = screen.getByAltText('Test Gallery')
    expect(img.getAttribute('src')).toContain('/api/eh/thumb-proxy')
    expect(img.getAttribute('loading')).toBe('lazy')
  })

  it('marks the list card thumbnail lazy so offscreen tiles issue no request', () => {
    render(<ListCard gallery={gallery} onClick={vi.fn()} onUploaderClick={vi.fn()} />)

    const img = screen.getByAltText('Test Gallery')
    expect(img.getAttribute('src')).toContain('/api/eh/thumb-proxy')
    expect(img.getAttribute('loading')).toBe('lazy')
  })
})
