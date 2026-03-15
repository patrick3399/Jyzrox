import { describe, it, expect, vi } from 'vitest'
import { getSourceStyle, getEventPosition } from '@/lib/galleryUtils'
import type { Gallery } from '@/lib/types'

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

// Minimal Gallery stub — only fields read by getSourceStyle
function makeGallery(source: string, import_mode: string | null = null): Gallery {
  return {
    id: 1,
    source,
    source_id: '',
    title: '',
    title_jpn: '',
    category: '',
    language: '',
    pages: 0,
    posted_at: null,
    added_at: '',
    rating: 0,
    favorited: false,
    is_favorited: false,
    my_rating: null,
    uploader: '',
    artist_id: null,
    download_status: 'complete',
    import_mode,
    tags_array: [],
  }
}

describe('getSourceStyle', () => {
  it('test_getSourceStyle_ehentai_returns_ehentai_label_and_purple_class', () => {
    const result = getSourceStyle(makeGallery('ehentai'))
    expect(result.label).toBe('E-Hentai')
    expect(result.className).toContain('purple')
  })

  it('test_getSourceStyle_pixiv_returns_pixiv_label_and_blue_class', () => {
    const result = getSourceStyle(makeGallery('pixiv'))
    expect(result.label).toBe('Pixiv')
    expect(result.className).toContain('blue')
  })

  it('test_getSourceStyle_local_link_returns_monitored_i18n_key_and_teal_class', () => {
    const result = getSourceStyle(makeGallery('local', 'link'))
    expect(result.label).toBe('library.monitored')
    expect(result.className).toContain('teal')
  })

  it('test_getSourceStyle_local_copy_returns_imported_i18n_key_and_amber_class', () => {
    const result = getSourceStyle(makeGallery('local', 'copy'))
    expect(result.label).toBe('library.imported')
    expect(result.className).toContain('amber')
  })

  it('test_getSourceStyle_local_no_import_mode_returns_local_label_and_green_class', () => {
    const result = getSourceStyle(makeGallery('local', null))
    expect(result.label).toBe('Local')
    expect(result.className).toContain('green')
  })

  it('test_getSourceStyle_unknown_source_returns_capitalised_label_and_vault_class', () => {
    const result = getSourceStyle(makeGallery('twitter'))
    expect(result.label).toBe('Twitter')
    expect(result.className).toContain('vault')
  })
})

// Minimal event stubs — only fields read by getEventPosition

function makeTouchEvent(touches: { clientX: number; clientY: number }[], changedTouches: { clientX: number; clientY: number }[] = []) {
  return {
    touches: { length: touches.length, ...touches } as unknown as React.TouchEvent['touches'],
    changedTouches: { length: changedTouches.length, ...changedTouches } as unknown as React.TouchEvent['changedTouches'],
  } as unknown as React.TouchEvent
}

function makeMouseEvent(clientX: number, clientY: number) {
  return { clientX, clientY } as unknown as React.MouseEvent
}

describe('getEventPosition', () => {
  it('test_getEventPosition_touch_event_with_touches_returns_touches0_coords', () => {
    const event = makeTouchEvent([{ clientX: 42, clientY: 99 }])
    expect(getEventPosition(event)).toEqual({ x: 42, y: 99 })
  })

  it('test_getEventPosition_touch_event_with_only_changedTouches_returns_changedTouches0_coords', () => {
    const event = makeTouchEvent([], [{ clientX: 10, clientY: 20 }])
    expect(getEventPosition(event)).toEqual({ x: 10, y: 20 })
  })

  it('test_getEventPosition_mouse_event_returns_clientX_clientY', () => {
    const event = makeMouseEvent(300, 150)
    expect(getEventPosition(event)).toEqual({ x: 300, y: 150 })
  })
})
