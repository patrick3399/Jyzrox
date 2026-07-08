import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from '@/lib/api'

// ── Helpers ───────────────────────────────────────────────────────────

/** Stub `fetch` so it resolves with the given JSON body, and return the spy. */
function mockFetchJson(body: unknown): ReturnType<typeof vi.fn> {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
    text: vi.fn().mockResolvedValue(JSON.stringify(body)),
  } as unknown as Response)
  vi.stubGlobal('fetch', spy)
  return spy
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('novels knowledge-index API client', () => {
  it('exposes graph/notes/appearances/reindex methods', () => {
    expect(typeof api.novels.graph).toBe('function')
    expect(typeof api.novels.notes).toBe('function')
    expect(typeof api.novels.appearances).toBe('function')
    expect(typeof api.novels.reindex).toBe('function')
  })

  it('listWorkFiles hits /files with encoded work and category', async () => {
    const spy = mockFetchJson({ files: [] })
    await api.novels.listWorkFiles('作品A', 'scrap')
    expect(spy).toHaveBeenCalledWith(
      `/api/novels/works/${encodeURIComponent('作品A')}/files?category=scrap`,
      expect.anything(),
    )
  })
})
