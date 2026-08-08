import { describe, it, expect } from 'vitest'
import { isReaderPath } from '@/lib/readerRoutes'

describe('isReaderPath — routes that own their own horizontal gestures', () => {
  it('matches the library reader', () => {
    expect(isReaderPath('/reader/123')).toBe(true)
  })

  // Regression: the E-Hentai proxy reader mounts the same Reader component,
  // whose swipeRight turns the page, but LayoutShell only exempted '/reader/'.
  // A left-edge rightward swipe there fired the Reader page turn and the global
  // back gesture at once, so the reader navigated away mid-read.
  it('matches the E-Hentai proxy reader, which mounts the same Reader', () => {
    expect(isReaderPath('/e-hentai/read/123/abcdef')).toBe(true)
  })

  it('does not match the E-Hentai gallery detail page', () => {
    expect(isReaderPath('/e-hentai/123/abcdef')).toBe(false)
  })

  it('does not match the E-Hentai browse list', () => {
    expect(isReaderPath('/e-hentai')).toBe(false)
  })

  it('does not match the reader settings page', () => {
    expect(isReaderPath('/settings/reader')).toBe(false)
  })
})
