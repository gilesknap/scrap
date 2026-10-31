import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import type { Plugin, Rollup } from "vite";
import { defineConfig } from "vitest/config";

// Lazy chunks the service worker keeps too, so they work offline: the composer and editor
// (and pageedit, a page's in the editor), the Markdown renderer, what Share and Download do
// (sharing, loaded on the first tap of either), the search screen's Filters (refine) and its
// recent searches (searches; without it, after a cold start offline, search works but shows
// no Recent), and the top bar's Back on a page opened cold (back; a stalled fetch of it would
// leave Back dead, its time limit being in it), and the photo panel on a page (figure: an old
// shell's hashed file is gone after a deploy, which leaves a page with bare photos). They are not loaded until used, so they are
// not part of the shell's size budget. (Mermaid, for diagrams, is not kept: it is big.)
export const OFFLINE = [
  "back",
  "composer",
  "downscale",
  "editor",
  "figure",
  "page",
  "pageedit",
  "render",
  "sharing",
  "refine",
  "searches",
];

// The files the app shell needs: what the entry chunks import statically, and their CSS
// and assets, plus the OFFLINE chunks. The drawing viewer (Excalidraw and React, loaded by a
// dynamic import) and its fonts are left out: they are fetched only when a drawing is shown.
function staticGraph(bundle: Rollup.OutputBundle): string[] {
  const seen = new Set<string>();
  const visit = (name: string) => {
    const c = bundle[name];
    if (seen.has(name) || c?.type !== "chunk") return;
    seen.add(name);
    for (const f of c.viteMetadata?.importedCss ?? []) seen.add(f);
    for (const f of c.viteMetadata?.importedAssets ?? []) seen.add(f);
    for (const i of c.imports) visit(i);
    for (const i of c.dynamicImports) {
      const d = bundle[i];
      if (d?.type === "chunk" && OFFLINE.includes(d.name)) visit(i);
    }
  };
  for (const [name, c] of Object.entries(bundle)) if (c.type === "chunk" && c.isEntry) visit(name);
  return [...seen];
}

// Fill the service worker's shell list and build id once the bundle is known.
const shell: Plugin = {
  name: "scrap-shell",
  apply: "build",
  enforce: "post", // after Vite has added index.html to the bundle
  generateBundle(_, bundle) {
    const sw = bundle["sw.js"];
    if (sw?.type !== "chunk") throw new Error("no sw.js in the bundle");
    const pub = readdirSync("public");
    const files = [...staticGraph(bundle), ...pub]
      .filter((f) => f !== "sw.js" && f !== "index.html" && !f.endsWith(".map"))
      .map((f) => `/${f}`);
    const list = ["/", ...files].join(",");
    const hash = createHash("sha256").update(list + sw.code);
    for (const f of pub) hash.update(readFileSync(`public/${f}`)); // an icon edit is a new build
    const index = bundle["index.html"];
    if (index?.type !== "asset") throw new Error("no index.html in the bundle");
    hash.update(index.source); // an index.html edit is a new build too
    const build = hash.digest("hex").slice(0, 12);
    for (const p of ["%SHELL%", "%BUILD%"]) {
      if (!sw.code.includes(p)) throw new Error(`sw.js lost its ${p} placeholder`);
    }
    sw.code = sw.code.replaceAll("%SHELL%", list).replaceAll("%BUILD%", build);
  },
};

// Excalidraw's drawing fonts, served by scrap at /excalidraw/fonts/ (EXCALIDRAW_ASSET_PATH)
// rather than from its CDN. All but Xiaolai (CJK, 14 MB): CJK text falls back to a system
// font. Excalidraw's UI font (Assistant) comes with its CSS. All are OFL or MIT licensed:
// see docs/how-to/use-the-pwa.md.
const FONTS = "node_modules/@excalidraw/excalidraw/dist/prod/fonts";
const FAMILIES = ["Excalifont", "Virgil", "Nunito", "Lilita", "ComicShanns", "Cascadia"];
FAMILIES.push("Liberation");
const fontFiles = () =>
  FAMILIES.flatMap((f) => readdirSync(`${FONTS}/${f}`).map((file) => `${f}/${file}`));
// Each font face Excalidraw registers lists our copy, then its CDN (esm.sh) as a fallback. The
// page's policy blocks the CDN, and Chrome still logs a violation for every face (about 11 per
// drawing, over 200 more for Xiaolai), burying real errors. The fallback becomes our own folder.
const ESM_FALLBACK = /"ASSETS_FALLBACK_URL",`https:\/\/esm\.sh\/.*?\/dist\/prod\/`\)/s;
const fonts: Plugin = {
  name: "scrap-excalidraw-fonts",
  transform(code, id) {
    if (!code.includes("ASSETS_FALLBACK_URL") || !id.includes("@excalidraw/excalidraw"))
      return null;
    if (!ESM_FALLBACK.test(code))
      this.error("Excalidraw's font fallback URL changed: update ESM_FALLBACK");
    return code.replace(
      ESM_FALLBACK,
      '"ASSETS_FALLBACK_URL",new URL("/excalidraw/",location.origin).href)',
    );
  },
  generateBundle() {
    for (const f of fontFiles()) {
      const source = readFileSync(`${FONTS}/${f}`);
      this.emitFile({ type: "asset", fileName: `excalidraw/fonts/${f}`, source });
    }
  },
  configureServer(server) {
    server.middlewares.use("/excalidraw/fonts/", (req, res, next) => {
      const f = decodeURIComponent((req.url ?? "").split("?")[0]).replace(/^\/+/, "");
      if (!fontFiles().includes(f)) return next();
      res.setHeader("Content-Type", "font/woff2");
      res.end(readFileSync(`${FONTS}/${f}`));
    });
  },
};

export default defineConfig({
  plugins: [shell, fonts],
  // Excalidraw's build reads it; React, not Preact
  define: { "process.env.IS_PREACT": JSON.stringify("false") },
  build: {
    outDir: "../src/scrap/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 3000, // the drawing viewer's chunk is big, and lazy
    rollupOptions: {
      input: { main: "index.html", sw: "src/sw.ts" },
      onwarn(warning, warn) {
        if (warning.code !== "MODULE_LEVEL_DIRECTIVE") warn(warning); // React's "use client"
      },
      output: { entryFileNames: (c) => (c.name === "sw" ? "sw.js" : "assets/[name]-[hash].js") },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/share": "http://127.0.0.1:8000" } },
  test: { include: ["tests/**/*.test.ts"] },
});
