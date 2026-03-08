/**
 * api.ts — Vitest test suite
 *
 * Covers:
 *   apiFetch  – credentials: 'include' always sent
 *   apiFetch  – non-2xx response throws an Error with the server detail message
 *   apiFetch  – non-2xx response falls back to "HTTP <status>" when body has no detail
 *   apiFetch  – 204 No Content returns empty object without attempting JSON.parse
 *   apiFetch  – successful JSON response is parsed and returned
 *   qs()      – array values are expanded as repeated keys (tags=a&tags=b)
 *   qs()      – scalar values are serialised normally
 *   qs()      – undefined / null values are omitted
 *   qs()      – empty params return an empty string (no leading '?')
 *
 * NOTE: qs() is not exported from api.ts.  We test it indirectly through the
 * public API surface (e.g. api.library.getGalleries) so that the tests remain
 * black-box and do not depend on implementation internals.  Where a direct
 * unit test of qs() is needed we extract the logic via the observable URL
 * passed to fetch.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Helpers ───────────────────────────────────────────────────────────

/**
 * Build a minimal Response-like object that satisfies the fetch contract
 * used by apiFetch.
 */
function makeResponse(options: {
  status?: number
  ok?: boolean
  body?: string        // raw text returned by res.text()
  jsonBody?: unknown   // if set, body is JSON.stringify(jsonBody)
}): Response {
  const status = options.status ?? 200
  const ok = options.ok ?? (status >= 200 && status < 300)
  const bodyText =
    options.jsonBody !== undefined
      ? JSON.stringify(options.jsonBody)
      : (options.body ?? '')

  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(
      options.jsonBody !== undefined ? options.jsonBody : {}
    ),
    text: vi.fn().mockResolvedValue(bodyText),
  } as unknown as Response
}

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

// We import the api object after stubbing fetch so the module picks up our mock.
// Vitest re-uses the module between tests in the same file, which is fine here
// because we reset the fetch mock via clearAllMocks in afterEach.

// ── apiFetch behaviour ────────────────────────────────────────────────

describe('apiFetch', () => {
  it('should always include credentials: "include" in the fetch call', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { status: 'ok' } })
    )

    await api.auth.logout()

    expect(fetch).toHaveBeenCalledOnce()
    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect((init as RequestInit).credentials).toBe('include')
  })

  it('should send Content-Type: application/json header by default', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { status: 'ok' } })
    )

    await api.auth.logout()

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const headers = new Headers(init?.headers as HeadersInit)
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('should throw an error with the server detail message on non-2xx response', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({
        status: 403,
        ok: false,
        jsonBody: { detail: 'Access denied' },
      })
    )

    await expect(api.auth.login('wrong', 'pass')).rejects.toThrow('Access denied')
  })

  it('should throw "HTTP <status>" when the error body has no detail field', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({
        status: 500,
        ok: false,
        jsonBody: { error: 'internal' }, // no `detail` key
      })
    )

    await expect(api.system.health()).rejects.toThrow('HTTP 500')
  })

  it('should throw "HTTP <status>" when the error body is not valid JSON', async () => {
    const { api } = await import('../lib/api')

    // Simulate res.json() failing (e.g. server returned HTML)
    const badResponse = {
      ok: false,
      status: 502,
      json: vi.fn().mockRejectedValue(new SyntaxError('Unexpected token')),
      text: vi.fn().mockResolvedValue('Bad Gateway'),
    } as unknown as Response

    vi.mocked(fetch).mockResolvedValueOnce(badResponse)

    await expect(api.system.info()).rejects.toThrow('HTTP 502')
  })

  it('should return parsed JSON on a successful 200 response', async () => {
    const { api } = await import('../lib/api')

    const payload = { total: 2, page: 1, galleries: [] }
    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: payload })
    )

    const result = await api.library.getGalleries()
    expect(result).toEqual(payload)
  })

  it('should return an empty object and NOT call JSON.parse on a 204 response', async () => {
    const { api } = await import('../lib/api')

    // 204 has no body — res.text() returns ''
    const noContentResponse = makeResponse({ status: 204, body: '' })
    vi.mocked(fetch).mockResolvedValueOnce(noContentResponse)

    const result = await api.library.saveProgress(1, 5)

    // An empty string body means the `text ? JSON.parse(text) : {}` branch
    // returns the fallback empty object.
    expect(result).toEqual({})

    // res.text() was called once; res.json() must NOT have been called
    // (apiFetch uses res.text() + manual JSON.parse, never res.json() on success).
    expect(noContentResponse.json).not.toHaveBeenCalled()
  })

  it('should call the correct endpoint URL', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: {} })
    )

    await api.library.getGallery(42)

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/library/galleries/42')
  })
})

// ── qs() behaviour (tested via observable fetch URL) ─────────────────

describe('qs() query-string builder', () => {
  it('should expand array values as repeated keys (tags=a&tags=b)', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({ tags: ['action', 'romance'] } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    const search = new URL(url as string, 'http://localhost').searchParams

    // Both values must be present under the same key.
    expect(search.getAll('tags')).toEqual(['action', 'romance'])
  })

  it('should serialise scalar string values normally', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({ query: 'naruto' } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    const search = new URL(url as string, 'http://localhost').searchParams

    expect(search.get('query')).toBe('naruto')
  })

  it('should serialise numeric values as strings', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({ page: 3 } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    const search = new URL(url as string, 'http://localhost').searchParams

    expect(search.get('page')).toBe('3')
  })

  it('should omit undefined values from the query string', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({ query: undefined } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    // The URL should have no query string at all.
    expect(url).toBe('/api/library/galleries')
  })

  it('should omit null values from the query string', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({ query: null } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/library/galleries')
  })

  it('should return no query string (no leading ?) when params object is empty', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({})

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/library/galleries')
  })

  it('should handle an empty array value by emitting no keys for that param', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    // An empty array: forEach does nothing, so the key should not appear.
    await api.library.getGalleries({ tags: [] } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/library/galleries')
  })

  it('should correctly combine multiple params including a mixed array+scalar', async () => {
    const { api } = await import('../lib/api')

    vi.mocked(fetch).mockResolvedValueOnce(
      makeResponse({ jsonBody: { total: 0, page: 1, galleries: [] } })
    )

    await api.library.getGalleries({ page: 2, tags: ['action', 'romance'] } as never)

    const [url] = vi.mocked(fetch).mock.calls[0]
    const search = new URL(url as string, 'http://localhost').searchParams

    expect(search.get('page')).toBe('2')
    expect(search.getAll('tags')).toEqual(['action', 'romance'])
  })
})
