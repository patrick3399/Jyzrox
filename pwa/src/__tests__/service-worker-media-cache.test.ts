import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createContext, runInContext } from 'node:vm'
import { beforeEach, describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'public/sw.template.js'), 'utf8')

const ORIGIN = 'https://jyzrox.test'

interface Stats {
  network: number
  cacheMatch: number
  cacheKeys: number
  cachePut: number
}

interface Harness {
  stats: Stats
  /** Drive the SW `fetch` handler and resolve what it responds with. */
  request: (url: string) => Promise<Response>
  /** Seed the media cache as if the image had already been fetched once. */
  seedMedia: (url: string, bytes?: number) => Promise<void>
  /** Let fire-and-forget work (cache writes, eviction sweeps) settle. */
  settle: () => Promise<void>
}

/**
 * Evaluate the real sw.template.js in a sandbox with a fake CacheStorage so we
 * can observe what it actually does per request. The sibling
 * service-worker-template.test.ts asserts on source text, which cannot catch
 * behavioral regressions like "how many cache reads does one image cost".
 */
function loadServiceWorker(): Harness {
  const stats: Stats = { network: 0, cacheMatch: 0, cacheKeys: 0, cachePut: 0 }
  const listeners = new Map<string, (event: unknown) => void>()
  const caches_ = new Map<string, FakeCache>()

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
      open: async (name: string) => getCache(name),
      delete: async (name: string) => caches_.delete(name),
      keys: async () => [...caches_.keys()],
    },
    fetch: async () => {
      stats.network++
      return new Response('imagebytes', {
        status: 200,
        headers: { 'Content-Length': '10000', 'Content-Type': 'image/webp' },
      })
    },
    indexedDB: { open: () => ({}) },
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

  return {
    stats,
    async request(url: string) {
      let responded: Promise<Response> | undefined
      fetchHandler({
        request: new Request(url),
        respondWith: (p: Promise<Response>) => {
          responded = p
        },
        waitUntil: () => {},
      })
      if (!responded) throw new Error(`SW did not respondWith for ${url}`)
      return responded
    },
    async seedMedia(url: string, bytes = 10000) {
      const cache = getCache('jyzrox-media')
      await cache.put(
        url,
        new Response('imagebytes', {
          status: 200,
          headers: {
            'Content-Length': String(bytes),
            'X-Cache-Time': String(Date.now()),
          },
        }),
      )
      stats.cachePut = 0
    },
    async settle() {
      for (let i = 0; i < 50; i++) await Promise.resolve()
      await new Promise((r) => setTimeout(r, 0))
      for (let i = 0; i < 50; i++) await Promise.resolve()
    },
  }
}

const IMG = `${ORIGIN}/media/image/insecure/rs:fit:400:0:0/bG9jYWw6Ly8vY2FzL2FhL2JiLndlYnA.webp`

describe('service worker media cache performance', () => {
  let sw: Harness

  beforeEach(() => {
    sw = loadServiceWorker()
  })

  it('serves an already-cached immutable image without a network round trip', async () => {
    // Regression (91af972): the media branch was flipped to network-first with
    // `cache: 'no-cache'`, so CacheStorage was only read when fetch() threw.
    // Every thumbnail hit the network on every render, defeating the
    // `Cache-Control: private, immutable` / 30d headers nginx already sends.
    // cas/thumbs/image are sha256 content-addressed capability URLs — the bytes
    // behind a URL can never change, so revalidation buys nothing.
    await sw.seedMedia(IMG)

    const res = await sw.request(IMG)
    await sw.settle()

    expect(res.status).toBe(200)
    expect(sw.stats.network).toBe(0)
  })

  it('does not rescan every cached entry when a media response is stored', async () => {
    // Regression (91af972): enforceMediaCacheLimit() moved from the cache-miss
    // path onto *every* media response. It walks the whole cache with a
    // sequential `await cache.match()` per entry, so with M entries cached each
    // image costs O(M) CacheStorage reads on the SW's single thread — and with
    // the 8GB default limit it evicts nothing, so the scan is pure waste.
    for (let i = 0; i < 40; i++) await sw.seedMedia(`${ORIGIN}/media/cas/seed/${i}.webp`)

    const cold = `${ORIGIN}/media/cas/cold/new.webp`
    await sw.request(cold)
    await sw.settle()

    // One miss lookup for the requested URL is fine; walking all 40 seeded
    // entries is the bug.
    expect(sw.stats.cacheMatch).toBeLessThan(10)
    expect(sw.stats.cacheKeys).toBe(0)
  })

  it('still revalidates mutable non-content-addressed media', async () => {
    // /media/avatars/ is NOT content-addressed: the same URL changes when the
    // user uploads a new avatar, so it must not be served cache-first forever.
    const avatar = `${ORIGIN}/media/avatars/7.png`
    await sw.seedMedia(avatar)

    await sw.request(avatar)
    await sw.settle()

    expect(sw.stats.network).toBe(1)
  })
})
