const CACHE_NAME = "omnivla-app-v19-fresh";
const APP_SHELL = ["/", "/assets/app.css?v=19", "/assets/app.js?v=19", "/manifest.webmanifest", "/assets/icons/omnivla-mark.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const requestUrl = new URL(event.request.url);
  if (requestUrl.pathname.startsWith("/api/") || requestUrl.pathname.startsWith("/overlay/")) return;

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            caches.open(CACHE_NAME).then((cache) => cache.put("/", response.clone()));
          }
          return response;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }

  // Network-first for application assets with fallback to cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok && requestUrl.origin === self.location.origin) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
