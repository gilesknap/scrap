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

const FAILED = [
  '<!doctype html><meta name="viewport" content="width=device-width"><title>scrap</title>',
  '<p style="font: 1.2rem system-ui; padding: 1rem">Not saved: the phone refused to store the',
  " share and the server could not be reached. Free some space, then share it again.</p>",
  '<p style="padding: 0 1rem"><a href="/">Open scrap</a></p>',
].join("");

// Shared photos are queued as they came: the downscale (downscale.ts) runs in the page, in
// Queue.addAll, and this worker does not use it (no decoding here, and the size is kept
// for the server to scale). See "Smaller photos" in docs/how-to/use-the-pwa.md.
async function share(request: Request): Promise<Response> {
  const copy = request.clone();
  const capture = fromShare(await request.formData());
  try {
    if (capture) await idb.put(newItem(capture));
    return Response.redirect(capture ? "/?shared=1" : "/", 303);
  } catch {
    // Storage refused it (full?): let the server's /share take it, else say so.
    return fetch(copy).catch(
      () => new Response(FAILED, { headers: { "Content-Type": "text/html" } }),
    );
  }
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
