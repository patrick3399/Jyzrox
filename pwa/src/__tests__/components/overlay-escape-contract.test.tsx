// FE-T25: while an overlay is open, Escape must close only that overlay. Detail pages bind
// Escape on window to "go back", so the overlay has to preventDefault + stopPropagation
// before the event reaches window. jsdom's fireEvent skips the microtask race, so the
// contract is asserted here at the component level.
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { Star } from 'lucide-react'
import type { ComponentType } from 'react'

const h = vi.hoisted(() => ({
  mockSearch: vi.fn(),
  mockFindSimilar: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/',
}))

vi.mock('swr', () => ({
  default: (key: unknown) => ({
    data: key ? { collections: [], similar: [] } : undefined,
    isLoading: false,
    error: undefined,
    mutate: vi.fn(),
  }),
  mutate: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  api: {
    saucenao: { search: h.mockSearch },
    library: { findSimilar: h.mockFindSimilar, batchGalleries: vi.fn() },
    collections: {
      list: vi.fn().mockResolvedValue({ collections: [] }),
      create: vi.fn(),
      addGalleries: vi.fn(),
      removeGallery: vi.fn(),
    },
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }))
vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/components/AppImage', () => ({ AppImage: () => null }))

import { GalleryActionsSheet } from '@/components/library/GalleryActionsSheet'
import { AddToCollectionMenu } from '@/components/library/AddToCollectionMenu'
import { SauceNaoModal } from '@/components/SauceNaoModal'
import { SimilarImagesPanel } from '@/components/SimilarImagesPanel'

function pressEscape(): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  act(() => {
    ;(document.activeElement ?? document.body).dispatchEvent(event)
  })
  return event
}

function asComponent(c: unknown) {
  return c as ComponentType<Record<string, unknown>>
}

let windowListener: Mock<(e: KeyboardEvent) => void>

beforeEach(() => {
  vi.clearAllMocks()
  h.mockSearch.mockReturnValue(new Promise(() => {}))
  h.mockFindSimilar.mockReturnValue(new Promise(() => {}))
  windowListener = vi.fn<(e: KeyboardEvent) => void>()
  window.addEventListener('keydown', windowListener)
})

afterEach(() => {
  window.removeEventListener('keydown', windowListener)
})

function expectContract(
  event: KeyboardEvent,
  closeCb: ReturnType<typeof vi.fn>,
  closeArgs?: unknown[],
) {
  // (a) close callback fired
  expect(closeCb).toHaveBeenCalled()
  if (closeArgs) expect(closeCb).toHaveBeenCalledWith(...closeArgs)
  // (b) default prevented
  expect(event.defaultPrevented).toBe(true)
  // (c) detail-page style window listener never saw it
  expect(windowListener).not.toHaveBeenCalled()
}

describe('overlay Escape contract (FE-T25)', () => {
  it('test_galleryActionsSheet_escape_does_not_reach_detail_page_window_listener', () => {
    const onClose = vi.fn()
    render(
      <GalleryActionsSheet
        open
        onClose={onClose}
        groups={[[{ id: 'a', label: 'Action A', icon: Star, onSelect: vi.fn() }]]}
      />,
    )
    expect(screen.getByText('Action A')).toBeInTheDocument()
    const event = pressEscape()
    expectContract(event, onClose)
  })

  it('test_addToCollectionMenu_escape_does_not_reach_detail_page_window_listener', () => {
    const onOpenChange = vi.fn()
    render(<AddToCollectionMenu galleryIds={[1]} onOpenChange={onOpenChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'collections.addToCollection' }))
    expect(screen.getByPlaceholderText('collections.newCollection')).toBeInTheDocument()
    onOpenChange.mockClear()
    const event = pressEscape()
    expectContract(event, onOpenChange, [false])
  })

  it('test_sauceNaoModal_escape_does_not_reach_detail_page_window_listener', () => {
    const onClose = vi.fn()
    const Modal = asComponent(SauceNaoModal)
    render(<Modal imageId={1} onClose={onClose} open />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    const event = pressEscape()
    expectContract(event, onClose)
  })

  it('test_similarImagesPanel_escape_does_not_reach_detail_page_window_listener', () => {
    const onClose = vi.fn()
    const Panel = asComponent(SimilarImagesPanel)
    render(<Panel imageId={1} onClose={onClose} open />)
    expect(screen.getByText('similar.title')).toBeInTheDocument()
    const event = pressEscape()
    expectContract(event, onClose)
  })
})
