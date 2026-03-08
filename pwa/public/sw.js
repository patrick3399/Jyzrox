const CACHE_NAME = 'jyzrox-static-v1';
const OFFLINE_URL = '/offline.html';

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
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // Cache-first for images/media if possible, otherwise network-first
  if (event.request.url.includes('/media/') || event.request.url.includes('/thumbs/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        // Only return cached response if it was a successful 2xx response
        if (cached && cached.status >= 200 && cached.status < 300) return cached;
        return fetch(event.request).then((response) => {
          // Only cache successful 2xx responses
          if (response.status >= 200 && response.status < 300) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        });
      })
    );
  } else {
    // Network first for other requests; fall back to cache or offline page
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Don't cache error responses from network
          if (response.status >= 200 && response.status < 300) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(event.request);
          // Only use cache if it contains a valid 2xx response
          if (cached && cached.status >= 200 && cached.status < 300) return cached;
          // For navigate requests show the offline fallback page
          if (event.request.mode === 'navigate') {
            return caches.match(OFFLINE_URL);
          }
          return new Response('', { status: 503 });
        })
    );
  }
});
