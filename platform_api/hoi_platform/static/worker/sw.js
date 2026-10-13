// Offline shell for the staff app. API calls always go to the network (never cached).
const CACHE = "hoi-staff-v12";
const SHELL = ["/worker/", "/worker/index.html", "/worker/app.css", "/worker/app.js", "/worker/i18n.js", "/worker/icon.svg", "/shared/brand/hoi/hoi-mark.svg", "/shared/brand/hoi/hoi-icon-192.png", "/shared/base.css", "/shared/voice.js", "/shared/roles.js",
  ...["hotel_manager", "front_office", "housekeeping", "fnb_service", "kitchen", "maintenance", "security", "storekeeper", "generic"].map((r) => `/shared/avatars/${r}.svg`)];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !SHELL.includes(url.pathname)) return;
  e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request)));
});
