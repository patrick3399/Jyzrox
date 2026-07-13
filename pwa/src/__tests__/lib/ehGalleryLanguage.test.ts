import { describe, expect, it } from 'vitest'
import { getEhGalleryLanguage } from '@/lib/ehGalleryLanguage'

describe('getEhGalleryLanguage', () => {
  it('prefers the canonical EH language tag', () => {
    expect(
      getEhGalleryLanguage({
        title: '[English] This title also says 中文',
        tags: ['language:korean', 'female:sole_female'],
      }),
    ).toBe('KO')
  })

  it('falls back to common title markers when list tags are unavailable', () => {
    expect(getEhGalleryLanguage({ title: '[中国語] 中文 sample', tags: [] })).toBe('ZH')
    expect(getEhGalleryLanguage({ title: '[English] sample', tags: [] })).toBe('EN')
  })

  it('returns null when neither tags nor title identify a language', () => {
    expect(getEhGalleryLanguage({ title: 'Untitled gallery', tags: [] })).toBeNull()
  })
})
