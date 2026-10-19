import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// Fill the service worker's shell list and build id once the bundle is known.
const shell: Plugin = {
  name: "scrap-shell",
  apply: "build",
  enforce: "post", // after Vite has added index.html to the bundle
  generateBundle(_, bundle) {
    const sw = bundle["sw.js"];
    if (sw?.type !== "chunk") throw new Error("no sw.js in the bundle");
    const pub = readdirSync("public");
    const files = [...Object.keys(bundle), ...pub]
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

export default defineConfig({
  plugins: [shell],
  build: {
    outDir: "../src/scrap/static",
    emptyOutDir: true,
    rollupOptions: {
      input: { main: "index.html", sw: "src/sw.ts" },
      output: { entryFileNames: (c) => (c.name === "sw" ? "sw.js" : "assets/[name]-[hash].js") },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/share": "http://127.0.0.1:8000" } },
  test: { include: ["tests/**/*.test.ts"] },
});
