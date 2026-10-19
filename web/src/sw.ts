/// <reference lib="webworker" />
// Service worker: caches the app shell only (never API answers or files) and turns a
// share-sheet POST into a queued capture. A new build changes this file (its shell list
// and build id), so the browser installs it; the page then offers "Update available".
import { idb } from "./db";
import { newItem } from "./queue";
import { fromShare } from "./share";

declare const self: ServiceWorkerGlobalScope;
const SHELL = "%SHELL%".split(","); // filled in by vite.config.ts
const CACHE = "scrap-%BUILD%";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (e) => e.data === "skipWaiting" && self.skipWaiting());

async function share(request: Request): Promise<Response> {
  const capture = fromShare(await request.formData());
  if (capture) await idb.put(newItem(capture));
  return Response.redirect(capture ? "/?shared=1" : "/", 303);
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (e.request.method === "POST" && url.pathname === "/share")
    return e.respondWith(share(e.request));
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname === "/healthz")
    return;
  // App routes all load the cached shell; everything else in the shell is cache-first.
  const key = e.request.mode === "navigate" ? "/" : e.request;
  e.respondWith(caches.match(key, { cacheName: CACHE }).then((hit) => hit ?? fetch(e.request)));
});
