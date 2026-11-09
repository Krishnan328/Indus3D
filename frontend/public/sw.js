/* Cache only this app's public shell and content-hashed assets, never printer data. */
const CACHE_NAME = "indus3d-cache-v2";
const CACHE_PREFIX = "indus3d-cache-";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

async function remember(request, response) {
  if (!response.ok || response.type !== "basic") return;
  try {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response.clone());
  } catch {
    // Storage denial or quota exhaustion must not hide a good network response.
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  const navigation = request.mode === "navigate" || url.pathname === "/" || url.pathname === "/index.html";
  const immutable = url.pathname.startsWith("/assets/");
  const shellAsset = ["/favicon.svg", "/manifest.json"].includes(url.pathname);
  if (!navigation && !immutable && !shellAsset) return;

  event.respondWith((async () => {
    if (immutable) {
      const cached = await caches.match(request);
      if (cached) return cached;
    }
    let response;
    try {
      response = await fetch(request, navigation || shellAsset ? { cache: "no-cache" } : undefined);
    } catch {
      const cached = await caches.match(request);
      return cached || Response.error();
    }
    await remember(request, response);
    return response;
  })());
});
