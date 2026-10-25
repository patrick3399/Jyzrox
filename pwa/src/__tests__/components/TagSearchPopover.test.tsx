import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockRouter = { back: vi.fn(), push: vi.fn(), replace: vi.fn() }

vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

import { TagSearchPopover } from '@/components/TagSearchPopover'
import { GalleryTagSection } from '@/components/library/GalleryTagSection'

function pushedQuery(): string {
  const url = mockRouter.push.mock.calls[0]?.[0] as string
  return new URL(url, 'http://localhost').searchParams.get('q') ?? ''
}

describe('tag click → local library search', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('test_tagSearchPopover_searchLocal_multiWordTag_quotesTheName', () => {
    const anchor = document.createElement('button')
    document.body.appendChild(anchor)
    render(
      <TagSearchPopover
        tag="cosplayer:jun ye tako"
        gallerySource="ehentai"
        anchorEl={anchor}
        onClose={() => {}}
      />,
    )

    fireEvent.click(screen.getByText('tags.searchLocal'))

    expect(pushedQuery()).toBe('"jun ye tako"')
  })

  it('test_galleryTagSection_localSource_multiWordTag_quotesTheName', () => {
    render(
      <GalleryTagSection
        source="local"
        tags={['female:big breasts']}
        tagData={[]}
        onUpdateTag={() => {}}
      />,
    )

    fireEvent.click(screen.getByText('big breasts'))

    expect(pushedQuery()).toBe('"big breasts"')
  })

  it('test_galleryTagSection_localSource_multiWordAiTag_quotesTheName', () => {
    render(
      <GalleryTagSection
        source="local"
        tags={[]}
        tagData={[{ namespace: 'general', name: 'long hair', confidence: 0.9, source: 'ai' }]}
        onUpdateTag={() => {}}
      />,
    )

    fireEvent.click(screen.getByText('long hair'))

    expect(pushedQuery()).toBe('"long hair"')
  })
})

// Regression: the popover closed on a document-level Escape, but the key event
// carried on to the detail page's window-level keydown handler, which treated
// the same Escape as "go back" — closing the popover also navigated away.
describe('Escape while the tag popover is open', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderPopover(onClose: () => void) {
    const anchor = document.createElement('button')
    document.body.appendChild(anchor)
    return render(
      <TagSearchPopover
        tag="female:glasses"
        gallerySource="local"
        anchorEl={anchor}
        onClose={onClose}
      />,
    )
  }

  it('closes the popover and does not reach window-level shortcuts', () => {
    const onClose = vi.fn()
    renderPopover(onClose)
    const windowSaw = vi.fn()
    window.addEventListener('keydown', windowSaw)
    try {
      fireEvent.keyDown(document.body, { key: 'Escape' })
    } finally {
      window.removeEventListener('keydown', windowSaw)
    }

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(windowSaw).not.toHaveBeenCalled()
  })

  it('marks the Escape as handled for listeners that run anyway', () => {
    renderPopover(() => {})
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })

    document.body.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(true)
  })

  it('leaves other keys alone', () => {
    const onClose = vi.fn()
    renderPopover(onClose)
    const windowSaw = vi.fn()
    window.addEventListener('keydown', windowSaw)
    try {
      fireEvent.keyDown(document.body, { key: 'Enter' })
    } finally {
      window.removeEventListener('keydown', windowSaw)
    }

    expect(onClose).not.toHaveBeenCalled()
    expect(windowSaw).toHaveBeenCalledTimes(1)
  })
})
