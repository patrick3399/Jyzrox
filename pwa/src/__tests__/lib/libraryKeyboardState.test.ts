import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearLibraryKeyboardTarget,
  consumeLibraryKeyboardTarget,
  saveLibraryKeyboardTarget,
} from '@/lib/libraryKeyboardState'

describe('libraryKeyboardState', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('restores the exact keyboard-entered gallery for the same query once', () => {
    saveLibraryKeyboardTarget('sort:rating', 842)

    expect(consumeLibraryKeyboardTarget('sort:rating')).toBe(842)
    expect(consumeLibraryKeyboardTarget('sort:rating')).toBeNull()
  })

  it('rejects a remembered gallery from a different query', () => {
    saveLibraryKeyboardTarget('favorited:true', 842)

    expect(consumeLibraryKeyboardTarget('')).toBeNull()
  })

  it('can clear a keyboard target after pointer navigation', () => {
    saveLibraryKeyboardTarget('', 842)
    clearLibraryKeyboardTarget()

    expect(consumeLibraryKeyboardTarget('')).toBeNull()
  })
})
