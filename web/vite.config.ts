import { createHash } from "node:crypto";
import { readdirSync } from "node:fs";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// Fill the service worker's shell list and build id once the bundle is known.
const shell: Plugin = {
  name: "scrap-shell",
  apply: "build",
  generateBundle(_, bundle) {
    const sw = bundle["sw.js"];
    if (sw?.type !== "chunk") throw new Error("no sw.js in the bundle");
    const files = [...Object.keys(bundle), ...readdirSync("public")]
      .filter((f) => f !== "sw.js" && f !== "index.html" && !f.endsWith(".map"))
      .map((f) => `/${f}`);
    const list = ["/", ...files].join(",");
    const build = createHash("sha256")
      .update(list + sw.code)
      .digest("hex")
      .slice(0, 12);
    sw.code = sw.code.replace("%SHELL%", list).replace("%BUILD%", build);
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
