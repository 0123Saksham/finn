// FINN service worker.
// Shell: network first, cached copy if offline. Fingerprinted /assets: cache first (they never change).
// Data: always network first (the brief must be fresh); the last good copy is only used when the
// network fails, so the brief and finished dossiers still open on a train or in a lift.
const SHELL = "finn-shell-v2";
const DATA = "finn-data-v1";
const OFFLINE_OK = /^\/api\/(digest|portfolio|demo|company\/|research\/|rules\/preview)/;

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/icon.svg", "/icon-192.png", "/manifest.webmanifest"])));
});

self.addEventListener("activate", (e) =>
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
);

const keep = (cache, req, res) => caches.open(cache).then((c) => c.put(req, res));

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const u = new URL(req.url);
  if (req.method !== "GET" || u.origin !== self.location.origin) return;

  if (u.pathname.startsWith("/api/")) {
    if (!OFFLINE_OK.test(u.pathname)) return;
    e.respondWith(
      fetch(req)
        .then((r) => {
          if (r.ok) {
            const cp = r.clone();
            // A research job polls while it runs; only a finished dossier is worth keeping.
            if (u.pathname.startsWith("/api/research/")) r.clone().json().then((j) => j.status === "done" && keep(DATA, req, cp)).catch(() => {});
            else keep(DATA, req, cp);
          }
          return r;
        })
        .catch(() => caches.match(req).then((r) => r || Response.error()))
    );
    return;
  }

  if (u.pathname.startsWith("/assets/")) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((r) => { keep(SHELL, req, r.clone()); return r; })));
    return;
  }

  e.respondWith(
    fetch(req)
      .then((r) => { if (r.ok) keep(SHELL, req, r.clone()); return r; })
      .catch(() => caches.match(req).then((r) => r || caches.match("/")))
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.openWindow("/"));
});
