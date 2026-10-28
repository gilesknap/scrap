// The scrap sim's build: the real app, with its routes in the URL's hash (sim.js), the fake
// server's scripts ahead of the app, relative paths and stable file names (so a republish
// replaces files rather than piling up hashed ones). No service worker.
import { mergeConfig, type Plugin, type UserConfig } from "vite";
import base from "../../vite.config.ts";

const SIM = process.env.SIM_DIR as string;

const sim: Plugin = {
  name: "scrap-sim",
  enforce: "pre",
  transform(code, id) {
    if (!id.includes("/web/src/") || !/\.ts$/.test(id)) return;
    return code.replace(/\blocation\.(pathname|search)\b/g, "__sim.loc.$1");
  },
  transformIndexHtml(html) {
    return html
      .replace(/<meta http-equiv="Content-Security-Policy"[^>]*>\s*/, "")
      .replace(/<link rel="manifest"[^>]*>\s*/, "")
      .replace('<small id="ver" aria-hidden="true"></small>', '<small id="ver" aria-hidden="true">v0.4.0</small>')
      .replace(/<title>[^<]*<\/title>/, "<title>scrap sim</title>")
      .replace(
        /(<script type="module")/,
        '<style>body { font: inherit }</style>\n    <script src="./sim-seed.js"></script>\n    <script src="./sim.js"></script>\n    $1',
      );
  },
};

const b = base as UserConfig;
const plugins = (b.plugins ?? []).filter((p) => (p as Plugin).name !== "scrap-shell");
export default mergeConfig(
  { ...b, plugins },
  {
    base: "./",
    plugins: [sim],
    build: {
      outDir: `${SIM}/out`,
      emptyOutDir: false,
      rollupOptions: {
        input: { main: "index.html" },
        output: {
          entryFileNames: "assets/[name].js",
          chunkFileNames: "assets/[name].js",
          assetFileNames: "assets/[name][extname]",
        },
      },
    },
  },
);
