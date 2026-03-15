const CACHE_NAME = 'jyzrox-static-0b93a332';
const OFFLINE_URL = '/offline.html';
const MEDIA_CACHE_NAME = 'jyzrox-media';
const PAGE_CACHE_NAME = 'jyzrox-pages';

// ── Cache Config (overridable via postMessage) ──
let cacheConfig = {
  mediaCacheTTLHours: 72,
  mediaCacheSizeMB: 8192,
  pageCacheTTLHours: 24,
};

// ── Offline Share Queue ──
const SHARE_QUEUE_DB = 'jyzrox-share-queue';
const SHARE_QUEUE_STORE = 'pending';

function openShareQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(SHARE_QUEUE_DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(SHARE_QUEUE_STORE, { autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function queueShareRequest(url) {
  const db = await openShareQueueDB();
  const tx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  tx.objectStore(SHARE_QUEUE_STORE).add({ url, timestamp: Date.now() });
  return new Promise((resolve) => { tx.oncomplete = resolve; });
}

async function replayShareQueue() {
  const db = await openShareQueueDB();
  const tx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  const store = tx.objectStore(SHARE_QUEUE_STORE);
  const items = await new Promise((resolve) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
  });

  for (const item of items) {
    try {
      await fetch('/api/download/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ url: item.url }),
      });
    } catch (e) {
      // Still offline, stop trying
      return;
    }
  }

  // Clear all successfully replayed items
  const clearTx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  clearTx.objectStore(SHARE_QUEUE_STORE).clear();
}

// Listen for online event to replay queue
self.addEventListener('online', () => {
  replayShareQueue();
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SW_CACHE_CONFIG') {
    cacheConfig = { ...cacheConfig, ...event.data.config };
  }
});

function wrapResponseWithTimestamp(response) {
  const headers = new Headers(response.headers);
  headers.set('X-Cache-Time', String(Date.now()));
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function isExpired(cachedResponse, ttlHours) {
  if (!ttlHours || ttlHours <= 0) return false;
  const cacheTime = cachedResponse.headers.get('X-Cache-Time');
  if (!cacheTime) return false;
  const age = Date.now() - Number(cacheTime);
  return age > ttlHours * 3600 * 1000;
}

async function enforceMediaCacheLimit() {
  if (!cacheConfig.mediaCacheSizeMB || cacheConfig.mediaCacheSizeMB <= 0) return;
  try {
    const cache = await caches.open(MEDIA_CACHE_NAME);
    const keys = await cache.keys();

    // Collect entries with their timestamps and sizes
    const entries = [];
    for (const request of keys) {
      const response = await cache.match(request);
      if (!response) continue;
      const cacheTime = Number(response.headers.get('X-Cache-Time') || '0');
      const size = Number(response.headers.get('Content-Length') || '0');
      entries.push({ request, cacheTime, size });
    }

    const totalSize = entries.reduce((sum, e) => sum + e.size, 0);
    const limitBytes = cacheConfig.mediaCacheSizeMB * 1024 * 1024;

    if (totalSize <= limitBytes) return;

    // Sort oldest first
    entries.sort((a, b) => a.cacheTime - b.cacheTime);

    let currentSize = totalSize;
    for (const entry of entries) {
      if (currentSize <= limitBytes) break;
      await cache.delete(entry.request);
      currentSize -= entry.size;
    }
  } catch (e) {
    // Non-critical, silently ignore
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Pre-cache core static assets including offline fallback
      return cache.addAll(['/', OFFLINE_URL]);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME && key !== MEDIA_CACHE_NAME && key !== PAGE_CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => {
      // Try to replay any queued share requests that were stored while offline
      return replayShareQueue();
    }).then(() => {
      return self.clients.claim();
    }).then(() => {
      return self.clients.matchAll({ type: 'window' });
    }).then((clients) => {
      clients.forEach((client) => client.postMessage({ type: 'SW_UPDATED' }));
    })
  );
});

self.addEventListener('fetch', (event) => {
  // Intercept POST requests to /api/download/ to support offline queuing
  if (event.request.method === 'POST' && event.request.url.includes('/api/download/')) {
    event.respondWith(
      fetch(event.request.clone()).catch(async () => {
        try {
          const body = await event.request.json();
          if (body.url) {
            await queueShareRequest(body.url);
            return new Response(JSON.stringify({
              job_id: 'offline-' + Date.now(),
              status: 'queued-offline',
            }), {
              headers: { 'Content-Type': 'application/json' },
            });
          }
        } catch (_) {
          // body parse failed — fall through to 503
        }
        return new Response('', { status: 503 });
      })
    );
    return;
  }

  if (event.request.method !== 'GET') return;

  // Cache-first for images/media if possible, otherwise network-first
  if (event.request.url.includes('/media/') || event.request.url.includes('/thumbs/')) {
    event.respondWith(
      caches.open(MEDIA_CACHE_NAME).then((cache) => {
        return cache.match(event.request).then((cached) => {
          if (cached && cached.status >= 200 && cached.status < 300) {
            if (!isExpired(cached, cacheConfig.mediaCacheTTLHours)) return cached;
            cache.delete(event.request);
          }
          return fetch(event.request).then((response) => {
            if (response.status >= 200 && response.status < 300) {
              const stamped = wrapResponseWithTimestamp(response.clone());
              cache.put(event.request, stamped);
              enforceMediaCacheLimit();
            }
            return response;
          });
        });
      })
    );
  } else {
    // Network first for other requests; fall back to cache or offline page
    event.respondWith(
      caches.open(PAGE_CACHE_NAME).then((cache) => {
        return fetch(event.request)
          .then((response) => {
            if (response.status >= 200 && response.status < 300) {
              const stamped = wrapResponseWithTimestamp(response.clone());
              cache.put(event.request, stamped);
            }
            return response;
          })
          .catch(async () => {
            const cached = await cache.match(event.request);
            if (cached && cached.status >= 200 && cached.status < 300) {
              if (!isExpired(cached, cacheConfig.pageCacheTTLHours)) return cached;
              cache.delete(event.request);
            }
            if (event.request.mode === 'navigate') {
              return caches.match(OFFLINE_URL);
            }
            return new Response('', { status: 503 });
          });
      })
    );
  }
});
