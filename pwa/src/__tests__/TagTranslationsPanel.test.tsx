import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import type { TagTranslationBrowseResponse } from '@/lib/types'

// ---------------------------------------------------------------------------
// Shared mock state
// ---------------------------------------------------------------------------

const h = vi.hoisted(() => ({
  data: {
    total: 2,
    items: [
      { namespace: 'artist', name: 'foo', language: 'zh', translation: '福' },
      { namespace: 'general', name: 'bar', language: 'zh', translation: '巴' },
    ],
  } as TagTranslationBrowseResponse,
}))

const mockTranslationsBrowse = vi.fn()
const mockUpsertTranslation = vi.fn()
const mockMutate = vi.fn()

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// The real `useSWR` would only re-invoke the fetcher when the key changes, but
// for these tests we just need the fetcher (and thus api.tags.translationsBrowse)
// to run with whatever params the component currently derives, so every render
// simply calls it and returns the shared mock payload.
vi.mock('swr', () => ({
  default: (key: unknown, fetcher?: (k: unknown) => unknown) => {
    if (key && fetcher) fetcher(key)
    return { data: h.data, mutate: mockMutate }
  },
}))

vi.mock('@/lib/api', () => ({
  api: {
    tags: {
      translationsBrowse: (...args: unknown[]) => mockTranslationsBrowse(...args),
      upsertTranslation: (...args: unknown[]) => mockUpsertTranslation(...args),
    },
  },
}))

import TagTranslationsPanel from '@/components/TagTranslationsPanel'

describe('TagTranslationsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.data = {
      total: 2,
      items: [
        { namespace: 'artist', name: 'foo', language: 'zh', translation: '福' },
        { namespace: 'general', name: 'bar', language: 'zh', translation: '巴' },
      ],
    }
    mockTranslationsBrowse.mockResolvedValue(h.data)
    mockUpsertTranslation.mockResolvedValue({ status: 'ok' })
  })

  it('renders translation rows returned by the API', () => {
    render(<TagTranslationsPanel isAdmin={false} />)

    expect(screen.getByText('artist')).toBeInTheDocument()
    expect(screen.getByText('foo')).toBeInTheDocument()
    expect(screen.getByText('福')).toBeInTheDocument()
    expect(screen.getByText('general')).toBeInTheDocument()
    expect(screen.getByText('bar')).toBeInTheDocument()
    expect(screen.getByText('巴')).toBeInTheDocument()
  })

  it('debounces the search input 300ms before calling the API with q', () => {
    vi.useFakeTimers()
    render(<TagTranslationsPanel isAdmin={false} />)
    mockTranslationsBrowse.mockClear()

    fireEvent.change(screen.getByPlaceholderText('tags.translationsBrowseSearchPlaceholder'), {
      target: { value: 'blue' },
    })

    // The debounce timer has not fired yet — no call should carry q=blue.
    expect(mockTranslationsBrowse).not.toHaveBeenCalledWith(
      expect.objectContaining({ q: 'blue' }),
    )

    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(mockTranslationsBrowse).toHaveBeenCalledWith(expect.objectContaining({ q: 'blue' }))

    vi.useRealTimers()
  })

  it('shows the inline edit control for admin users but not for viewers', () => {
    const { rerender } = render(<TagTranslationsPanel isAdmin={false} />)
    expect(screen.queryByText('tags.editTranslation')).not.toBeInTheDocument()

    rerender(<TagTranslationsPanel isAdmin={true} />)
    expect(screen.getAllByText('tags.editTranslation').length).toBeGreaterThan(0)
  })

  it('saving an edited zh-TW row sends language=zh (DB language) to upsertTranslation', async () => {
    render(<TagTranslationsPanel isAdmin={true} />)

    fireEvent.change(screen.getByLabelText('tags.translationLanguage'), {
      target: { value: 'zh-TW' },
    })

    const editButtons = screen.getAllByText('tags.editTranslation')
    fireEvent.click(editButtons[0])

    const input = screen.getByDisplayValue('福')
    fireEvent.change(input, { target: { value: '福貓' } })
    fireEvent.click(screen.getByText('common.save'))

    await waitFor(() =>
      expect(mockUpsertTranslation).toHaveBeenCalledWith(
        expect.objectContaining({
          namespace: 'artist',
          name: 'foo',
          language: 'zh',
          translation: '福貓',
        }),
      ),
    )
  })

  it('shows the empty state when there are no items', () => {
    h.data = { total: 0, items: [] }

    render(<TagTranslationsPanel isAdmin={false} />)

    expect(screen.getByText('tags.translationsBrowseEmpty')).toBeInTheDocument()
  })
})
