// Size budget for the built PWA (run after `npm run build`): the app shell that every screen
// loads must stay small, and must not pull in the drawing viewer (Excalidraw and React), which
// is loaded only when a drawing is shown. Prints both, gzipped.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const OUT = new URL("../../src/scrap/static/", import.meta.url).pathname;
const BUDGET = 15 * 1024; // the shell's JavaScript, gzipped (11.6 kB before drawings, 13.7 after)

const gz = (file) => gzipSync(readFileSync(join(OUT, file))).length;
const kb = (n) => `${(n / 1024).toFixed(1)} kB`;

// Each chunk's static imports, from the import statements in the built files
const deps = (file) =>
  [
    ...readFileSync(join(OUT, file), "utf8").matchAll(
      /(?:import|from)\s*["']\.\/([\w.-]+\.js)["']/g,
    ),
  ].map((m) => `assets/${m[1]}`);
function graph(roots) {
  const seen = new Set();
  const visit = (f) => {
    if (seen.has(f)) return;
    seen.add(f);
    for (const d of deps(f)) visit(d);
  };
  for (const r of roots) visit(r);
  return seen;
}

const html = readFileSync(join(OUT, "index.html"), "utf8");
const entries = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.(?:js|css))"/g)].map(
  (m) => m[1],
);
const shell = graph(entries.filter((f) => f.endsWith(".js")));
const shellJs = [...shell].reduce((n, f) => n + gz(f), 0);
const shellCss = entries.filter((f) => f.endsWith(".css")).reduce((n, f) => n + gz(f), 0);

const assets = readdirSync(join(OUT, "assets"));
const board = assets.find((f) => /^excalidraw-[\w-]+\.js$/.test(f));
if (!board) throw new Error("no board chunk: is the drawing viewer still lazy?");
const viewer = graph([`assets/${board}`]);
const viewerJs = [...viewer].filter((f) => !shell.has(f)).reduce((n, f) => n + gz(f), 0);
const viewerCss = assets
  .filter((f) => f.endsWith(".css") && !entries.includes(`assets/${f}`))
  .reduce((n, f) => n + gz(`assets/${f}`), 0);

console.log(`app shell:      ${kb(shellJs)} JS + ${kb(shellCss)} CSS (budget ${kb(BUDGET)} JS)`);
console.log(
  `drawing viewer: ${kb(viewerJs)} JS + ${kb(viewerCss)} CSS, loaded when a drawing is shown`,
);
console.log(`viewer chunks:  ${[...viewer].filter((f) => !shell.has(f)).join(" ")}`);

let failed = false;
if (shellJs > BUDGET) {
  console.error("FAIL: the app shell is over its budget");
  failed = true;
}
const inShell = (text) => [...shell].some((f) => readFileSync(join(OUT, f), "utf8").includes(text));
if (shell.has(`assets/${board}`) || inShell("excalidraw-container") || inShell("react.dev")) {
  console.error("FAIL: the app shell imports the drawing viewer (Excalidraw or React)");
  failed = true;
}
process.exit(failed ? 1 : 0);
