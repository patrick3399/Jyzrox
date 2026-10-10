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
