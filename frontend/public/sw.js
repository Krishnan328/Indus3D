/**
 * Indus3D Progressive Web App Service Worker
 * Provides offline kiosk shell caching and background asset updates.
 */

const CACHE_NAME = "indus3d-cache-v1";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/favicon.svg",
  "/manifest.json",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((k) => {
          if (k !== CACHE_NAME) return caches.delete(k);
        })
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Network-first for all API, WebSocket, and telemetry calls
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/server") || e.request.method !== "GET") {
    return;
  }

  // Cache-first falling back to network for static assets
  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request).then((res) => {
        if (!res || res.status !== 200 || res.type !== "basic") {
          return res;
        }
        const toCache = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(e.request, toCache));
        return res;
      });
    })
  );
});
