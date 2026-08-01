// HAIP Service Worker
// __BUILD_ID__ is replaced at build time by scripts/set-build-id.js (npm
// `prebuild`/`predev`) with a git-short-SHA (or timestamp fallback) -- this
// file's own bytes now change on every real deploy automatically, which is
// what makes the browser's periodic byte-diff update check actually fire.
// Previously this was a hand-edited "v4" -> "v5" -> "v6" string; forgetting
// to bump it was the direct cause of several "why isn't my change showing
// up" service-worker cache-staleness sessions. The activate handler below
// deletes any cache whose name doesn't match, so a changed name is what
// evicts stale bundles from clients that already installed the old SW.
//
// This is the source of truth -- public/sw.js is generated from this file
// and gitignored. Edit this file, never public/sw.js directly (it gets
// overwritten on the next `npm run dev`/`npm run build`).
const CACHE_NAME = 'haip-shell-__BUILD_ID__';
const STATIC_CACHE_NAME = 'haip-static-__BUILD_ID__';

// App shell assets to cache on install — everything a cold offline load needs
// besides the hashed /_next/static bundles (those get cached as they're
// requested, since their filenames aren't known at SW build time).
const PRECACHE = [
  '/offline',
  '/manifest.json',
  '/icon.svg',
  '/icon-maskable.svg',
  '/app-icon.png',
];

self.addEventListener('install', (event) => {
  // No self.skipWaiting() here anymore -- a newly-installed SW now sits in
  // "waiting" (the browser's normal behavior) until the page explicitly
  // asks it to take over (see the message listener below). Previously this
  // called skipWaiting() unconditionally, so a new SW activated the moment
  // it finished installing -- combined with clients.claim() in activate and
  // the controllerchange->reload listener in PWARegister.tsx, that meant
  // every open tab got silently, forcibly reloaded on every deploy with no
  // warning, mid-keystroke if the user happened to be typing. C3's
  // UpdateBanner now owns that decision instead.
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE).catch(() => {}))
  );
});

// C4: the update banner's "Update now" click posts this to the waiting
// worker (via registration.waiting.postMessage) -- this is the only path
// that now triggers activation. Letting the SW activate on its own without
// this message is what the removed self.skipWaiting() call used to do.
self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== CACHE_NAME && k !== STATIC_CACHE_NAME)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // API calls always go live — never cached, never served stale
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/v1/')) return;

  // /_next/static/* is content-hashed by Next.js — immutable per build, so
  // cache-first is safe and gives the app shell's JS/CSS an offline cold start.
  if (url.pathname.startsWith('/_next/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          if (response.ok) {
            const cloned = response.clone();
            caches.open(STATIC_CACHE_NAME).then((cache) => cache.put(event.request, cloned));
          }
          return response;
        });
      })
    );
    return;
  }

  // Other /_next/ internals (RSC payloads, etc.) — always network, no caching
  if (url.pathname.startsWith('/_next/')) return;

  // Network-first strategy: try network, fall back to cache, fall back to offline page
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
        }
        return response;
      })
      .catch(() =>
        caches.match(event.request).then((cached) => {
          if (cached) return cached;
          // For navigation requests show offline page
          if (event.request.mode === 'navigate') {
            return caches.match('/offline').then((offlinePage) =>
              offlinePage ?? new Response('Offline', { status: 503, statusText: 'Service Unavailable' })
            );
          }
          return new Response('Network error', { status: 503 });
        })
      )
  );
});

// ── Push Notifications ────────────────────────────────────────────────────────
self.addEventListener('push', (event) => {
  const data = event.data?.json?.() ?? {};
  event.waitUntil(
    self.registration.showNotification(data.title || 'HAIP', {
      body: data.body || 'You have a new message',
      icon: '/icon.svg',
      badge: '/icon.svg',
      tag: data.tag || 'haip-notification',
      data: { url: data.url || '/dashboard/inbox' },
      actions: [
        { action: 'open', title: 'Open' },
        { action: 'dismiss', title: 'Dismiss' },
      ],
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.action === 'dismiss') return;
  const target = event.notification.data?.url || '/dashboard/inbox';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});
