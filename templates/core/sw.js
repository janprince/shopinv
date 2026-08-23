{% load static %}/* JCF Organic service worker.
 * Scope: shell caching only. Sales are never queued offline — a sale is not a
 * sale until the server has confirmed it, and pretending otherwise would be
 * worse than an honest error message.
 */
const CACHE = "jcf-shell-v3";
const SHELL = [
  "{% static 'css/fonts.css' %}",
  "{% static 'css/theme.css' %}",
  "{% static 'js/app.js' %}",
  "{% static 'js/pos.js' %}",
  "{% static 'vendor/bootstrap.min.css' %}",
  "{% static 'vendor/bootstrap.bundle.min.js' %}",
  "{% static 'vendor/htmx.min.js' %}",
  "{% url 'core:offline' %}"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Never touch anything that changes data.
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Static assets: cache first. Bump CACHE whenever the shell assets change so
  // an installed till does not keep yesterday's interface indefinitely.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
        return response;
      }))
    );
    return;
  }

  // Pages: always go to the network so figures are never stale; fall back to a
  // clear offline page rather than a browser error.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("{% url 'core:offline' %}"))
    );
  }
});
