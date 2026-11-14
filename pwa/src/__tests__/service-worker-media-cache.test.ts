import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createContext, runInContext } from 'node:vm'
import { beforeEach, describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'public/sw.template.js'), 'utf8')

const ORIGIN = 'https://jyzrox.test'
const LEGACY_MEDIA_CACHE = 'jyzrox-media-v2'
const PAGE_CACHE = 'jyzrox-pages'

interface Stats {
  network: number
  cacheOpen: number
  cacheMatch: number
  cacheKeys: number
  cachePut: number
  /** `clone()` calls on responses the fake network handed the worker. */
  responseClones: number
}

interface Harness {
  stats: Stats
  /** Drive the SW `fetch` handler and resolve what it responds with. */
  request: (url: string) => Promise<Response>
  /**
   * Drive the SW `fetch` handler without requiring it to respond. `responded`
   * is undefined when the worker declined the request and left it to the
   * browser's own network stack.
   */
  handle: (url: string) => { responded: Promise<Response> | undefined }
  /**
   * Prime the browser HTTP cache as if the resource had been fetched on an
   * earlier visit. A later plain `fetch()` is then served from disk with no
   * network round trip — how the browser answers an `immutable` response.
   */
  seedHttpCache: (url: string) => void
  /** Create a CacheStorage cache holding one entry, as an older worker left it. */
  seedCacheStorage: (name: string, url: string) => Promise<void>
  cacheNames: () => string[]
  /** Simulate loss of connectivity: uncached `fetch()` calls reject. */
  setOffline: (offline: boolean) => void
  /** Make the network answer this URL with the given HTTP status. */
  setResponseStatus: (url: string, status: number) => void
  /** Fire a lifecycle or message event and let its waitUntil() work run. */
  dispatch: (type: string, data?: unknown) => Promise<void>
  /** Let fire-and-forget work settle. */
  settle: () => Promise<void>
}

/**
 * Evaluate the real sw.template.js in a sandbox with a fake CacheStorage and a
 * fake browser HTTP cache so we can observe what it actually does per request.
 * The sibling service-worker-template.test.ts asserts on source text, which
 * cannot catch behavioral regressions like "does one image touch CacheStorage".
 */
function loadServiceWorker(): Harness {
  const stats: Stats = {
    network: 0,
    cacheOpen: 0,
    cacheMatch: 0,
    cacheKeys: 0,
    cachePut: 0,
    responseClones: 0,
  }
  const listeners = new Map<string, (event: unknown) => void>()
  const caches_ = new Map<string, FakeCache>()
  const httpCache = new Map<string, Response>()
  const pendingWork: Promise<unknown>[] = []
  let offline = false
  const responseStatus = new Map<string, number>()

  const keyOf = (req: Request | string) => (typeof req === 'string' ? req : req.url)

  class FakeCache {
    store = new Map<string, Response>()
    async match(req: Request | string) {
      stats.cacheMatch++
      return this.store.get(keyOf(req))
    }
    async put(req: Request | string, res: Response) {
      stats.cachePut++
      this.store.set(keyOf(req), res)
    }
    async keys() {
      stats.cacheKeys++
      return [...this.store.keys()].map((u) => new Request(u))
    }
    async delete(req: Request | string) {
      return this.store.delete(keyOf(req))
    }
    async addAll() {}
  }

  const getCache = (name: string) => {
    let c = caches_.get(name)
    if (!c) {
      c = new FakeCache()
      caches_.set(name, c)
    }
    return c
  }

  const sandbox: Record<string, unknown> = {
    self: {
      addEventListener: (type: string, fn: (event: unknown) => void) => listeners.set(type, fn),
      location: { origin: ORIGIN },
      registration: { sync: null },
      clients: { claim: async () => {}, matchAll: async () => [] },
      skipWaiting: () => {},
    },
    caches: {
      open: async (name: string) => {
        stats.cacheOpen++
        return getCache(name)
      },
      delete: async (name: string) => caches_.delete(name),
      keys: async () => [...caches_.keys()],
      match: async () => undefined,
    },
    fetch: async (req: Request | string, opts?: { cache?: string }) => {
      const url = typeof req === 'string' ? req : req.url
      // Model the browser HTTP cache. `only-if-cached` answers from disk (stale
      // or not) and fails on a miss; `no-cache` always revalidates over the
      // network; a plain fetch() of a resource seen before is served from disk.
      if (opts?.cache === 'only-if-cached') {
        const hit = httpCache.get(url)
        if (hit) return hit.clone()
        throw new TypeError('Failed to fetch')
      }
      if (opts?.cache !== 'no-cache') {
        const hit = httpCache.get(url)
        if (hit) return hit.clone()
      }
      if (offline) throw new TypeError('Failed to fetch')
      stats.network++
      const res = new Response('imagebytes', {
        status: responseStatus.get(url) ?? 200,
        headers: {
          'Content-Length': '10000',
          'Content-Type': 'image/webp',
          'Cache-Control': 'private, immutable',
        },
      })
      httpCache.set(url, res.clone())
      const handed = res.clone()
      const clone = handed.clone.bind(handed)
      handed.clone = () => {
        stats.responseClones++
        return clone()
      }
      return handed
    },
    // The share-queue DB never opens in this sandbox; activation's replay step
    // simply stays pending, which is fine for the cache assertions below.
    indexedDB: { open: () => ({}) },
    navigator: {},
    Response,
    Request,
    Headers,
    URL,
    setTimeout,
    clearTimeout,
    Date,
    console,
  }
  sandbox.globalThis = sandbox
  createContext(sandbox)
  runInContext(source, sandbox)

  const fetchHandler = listeners.get('fetch')
  if (!fetchHandler) throw new Error('sw.template.js registered no fetch handler')

  const flush = async () => {
    for (let i = 0; i < 50; i++) await Promise.resolve()
    await new Promise((r) => setTimeout(r, 0))
    for (let i = 0; i < 50; i++) await Promise.resolve()
  }

  return {
    stats,
    handle(url: string) {
      let responded: Promise<Response> | undefined
      fetchHandler({
        request: new Request(url),
        respondWith: (p: Promise<Response>) => {
          responded = p
        },
        waitUntil: (p: Promise<unknown>) => pendingWork.push(p),
      })
      return { responded }
    },
    async request(url: string) {
      const { responded } = this.handle(url)
      if (!responded) throw new Error(`SW did not respondWith for ${url}`)
      return responded
    },
    seedHttpCache(url: string) {
      httpCache.set(
        url,
        new Response('imagebytes', {
          status: 200,
          headers: { 'Content-Length': '10000', 'Cache-Control': 'private, immutable' },
        }),
      )
    },
    async seedCacheStorage(name: string, url: string) {
      getCache(name).store.set(url, new Response('imagebytes', { status: 200 }))
    },
    cacheNames() {
      return [...caches_.keys()]
    },
    setOffline(value: boolean) {
      offline = value
    },
    setResponseStatus(url: string, status: number) {
      responseStatus.set(url, status)
    },
    async dispatch(type: string, data?: unknown) {
      const handler = listeners.get(type)
      if (!handler) throw new Error(`sw.template.js registered no ${type} handler`)
      handler({ data, waitUntil: () => {} })
      await flush()
    },
    async settle() {
      await Promise.allSettled(pendingWork.splice(0))
      await flush()
    },
  }
}

const CONTENT_ADDRESSED = [
  `${ORIGIN}/media/image/insecure/rs:fit:400:0:0/bG9jYWw6Ly8vY2FzL2FhL2JiLndlYnA.webp`,
  `${ORIGIN}/media/thumbs/aa/bb/aabb_320.webp`,
  `${ORIGIN}/media/cas/aa/bb/aabb.jpg`,
]

describe('service worker media handling', () => {
  let sw: Harness

  beforeEach(() => {
    sw = loadServiceWorker()
  })

  it.each(CONTENT_ADDRESSED)(
    'leaves content-addressed media to the browser HTTP cache without touching CacheStorage: %s',
    async (url) => {
      // Regression (unbounded second copy): every sha256-addressed image was
      // stored twice — once in the browser HTTP cache (`immutable`, 7–30 days)
      // and again in a CacheStorage media cache whose size budget was lost on
      // every worker restart, checked at most every 10 minutes, and whose TTL
      // was never enforced. The browser already bounds and evicts its HTTP
      // cache, so the worker no longer handles these requests at all.
      const { responded } = sw.handle(url)
      await sw.settle()

      expect(responded).toBeUndefined()
      expect(sw.stats.cacheOpen).toBe(0)
      expect(sw.stats.cachePut).toBe(0)
      expect(sw.stats.responseClones).toBe(0)
    },
  )

  it('never copies path-addressed library media into CacheStorage', async () => {
    const page = `${ORIGIN}/media/libraries/jyzrox/images/Cosplay/a/027.jpg`

    const res = await sw.request(page)
    await sw.settle()

    expect(res.status).toBe(200)
    expect(sw.stats.cacheOpen).toBe(0)
    expect(sw.stats.cachePut).toBe(0)
    // No tee'd body: leaving a gallery of huge originals must not keep a
    // cache-write branch downloading in the worker (FE-T23).
    expect(sw.stats.responseClones).toBe(0)
  })

  it('still revalidates mutable path-addressed media even when the HTTP cache holds it', async () => {
    // /media/avatars/ is NOT content-addressed: the same URL changes when the
    // user uploads a new avatar, and nginx marks it `max-age=1d`.
    const avatar = `${ORIGIN}/media/avatars/7.png`
    sw.seedHttpCache(avatar)

    await sw.request(avatar)
    await sw.settle()

    expect(sw.stats.network).toBe(1)
  })

  it('does not mask a library 403 with a previously authorized HTTP-cached copy', async () => {
    // Revocation (high-risk invariant "a cached response must not hide a
    // current 401/403 for path-addressed media").
    const page = `${ORIGIN}/media/libraries/comfyui-output/private/001.png`
    sw.seedHttpCache(page)
    sw.setResponseStatus(page, 403)

    const res = await sw.request(page)
    await sw.settle()

    expect(res.status).toBe(403)
  })

  it('falls back to the HTTP-cached copy of library media when offline', async () => {
    const page = `${ORIGIN}/media/libraries/comfyui-output/Misc/AI/mp2/mp2_00001_.png`
    sw.seedHttpCache(page)
    sw.setOffline(true)

    const res = await sw.request(page)
    await sw.settle()

    expect(res.status).toBe(200)
    expect(sw.stats.network).toBe(0)
    expect(sw.stats.cacheOpen).toBe(0)
  })

  it('answers 503 for library media that is offline and was never cached', async () => {
    sw.setOffline(true)

    const res = await sw.request(`${ORIGIN}/media/libraries/comfyui-output/never/seen.png`)

    expect(res.status).toBe(503)
  })

  it('leaves video requests to the browser instead of routing them through the worker', async () => {
    // Regression (Reader video playback crash, FE-T16): responding to a video
    // means the worker holds a second copy of a body the <video> element is
    // already buffering, and media elements stream by Range anyway.
    for (const clip of [
      `${ORIGIN}/media/cas/2b/ff/2bff41ba.mp4`,
      `${ORIGIN}/media/libraries/jyzrox/videos/a/clip.webm`,
    ]) {
      const { responded } = sw.handle(clip)
      expect(responded).toBeUndefined()
    }
  })

  it('deletes the legacy media cache when the new worker activates', async () => {
    // Devices upgraded from the CacheStorage media store still hold up to the
    // old 8 GB default; nothing reads it any more, so activation reclaims it.
    await sw.seedCacheStorage(LEGACY_MEDIA_CACHE, `${ORIGIN}/media/cas/aa/bb.webp`)
    await sw.seedCacheStorage(PAGE_CACHE, `${ORIGIN}/library`)

    await sw.dispatch('activate')

    expect(sw.cacheNames()).not.toContain(LEGACY_MEDIA_CACHE)
    expect(sw.cacheNames()).toContain(PAGE_CACHE)
  })

  it('clears the page cache and any leftover legacy media cache on logout', async () => {
    // BR-003: cached private content must not outlive the session.
    await sw.seedCacheStorage(LEGACY_MEDIA_CACHE, `${ORIGIN}/media/cas/aa/bb.webp`)
    await sw.seedCacheStorage(PAGE_CACHE, `${ORIGIN}/library`)

    await sw.dispatch('message', { type: 'SW_CLEAR_USER_CACHES' })

    expect(sw.cacheNames()).not.toContain(LEGACY_MEDIA_CACHE)
    expect(sw.cacheNames()).not.toContain(PAGE_CACHE)
  })
})
