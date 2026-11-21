// A tiny static server for the demo: the demo sim under /art/x1/ (as the artifact host
// serves it) and sim/demo/'s own pages (stage, terminal, transcripts) under /demo/.
//   import { serve } from "./serve.mjs"; const { url, close } = await serve({ site, demo, port })
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
  ".jpg": "image/jpeg", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json",
  ".wasm": "application/wasm", ".txt": "text/plain",
};

export function serve({ site, demo, extra = {}, port = 0 }) {
  const roots = { "/art/x1/": site, "/demo/": demo, ...extra };
  const server = createServer(async (req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const pre = Object.keys(roots).find((p) => path.startsWith(p));
    if (!pre) return res.writeHead(404).end();
    let file = normalize(join(roots[pre], path.slice(pre.length)));
    if (!file.startsWith(normalize(roots[pre]))) return res.writeHead(403).end();
    try {
      if ((await stat(file)).isDirectory()) file = join(file, "index.html");
      const body = await readFile(file);
      const type = TYPES[extname(file)] || (extname(file) ? "application/octet-stream" : "image/jpeg");
      res.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" }).end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  return new Promise((ok) =>
    server.listen(port, "127.0.0.1", () =>
      ok({ url: `http://127.0.0.1:${server.address().port}`, close: () => server.close() }),
    ),
  );
}
