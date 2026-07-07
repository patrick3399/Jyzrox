import { describe, it, expect } from 'vitest'
import { api } from '@/lib/api'

describe('novels knowledge-index API client', () => {
  it('exposes graph/notes/appearances/reindex methods', () => {
    expect(typeof api.novels.graph).toBe('function')
    expect(typeof api.novels.notes).toBe('function')
    expect(typeof api.novels.appearances).toBe('function')
    expect(typeof api.novels.reindex).toBe('function')
  })
})
