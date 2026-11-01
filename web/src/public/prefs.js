// A public page's reader preferences (#519): the theme (light or dark) and the column's
// maximum width, kept in this browser. The site's one script outside Pagefind: the build
// (vite.config.ts publicAssets) copies it as is to src/scrap/static/public/prefs.js, which
// scrap pushes as /assets/prefs.js. Every page, tag page, home and the 404 load it from
// <head>, deferred and render-blocking (<script src="/assets/prefs.js" defer
// blocking="render">), so the kept choice is set on <html> before the first paint.
//
// - The theme: light, unless the reader chose dark (data-theme="dark" on <html>, tokens.css's
//   dark values; the build leaves out its prefers-color-scheme default for public pages, so
//   neither the device's setting nor a blocked script makes a page dark).
// - The width: --column on <html> (tokens.css's 800px when nothing is kept), as the app's
//   Settings > Maximum column width (column.ts) offers it.
// - The buttons: made here, in the site's header, so without the script there are none and
//   the page is simply light, at the default width.
(() => {
  const THEME = "scrap.public.theme";
  const COLUMN = "scrap.public.column";
  // As column.ts's COLUMNS: the default (800) is kept as nothing
  const WIDTHS = [
    ["720", "Narrow"],
    ["800", "Medium"],
    ["880", "Wide"],
    ["960", "Wider"],
  ];
  const root = document.documentElement;
  const get = (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null; // storage blocked: light, at the default width
    }
  };
  const put = (k, v) => {
    try {
      if (v === null) localStorage.removeItem(k);
      else localStorage.setItem(k, v);
    } catch {} // not kept: it still applies to this page
  };
  const theme = get(THEME);
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  const width = get(COLUMN);
  if (WIDTHS.some(([w]) => w === width)) root.style.setProperty("--column", `${width}px`);

  const isDark = () => root.dataset.theme === "dark";
  const current = () => {
    const w = root.style.getPropertyValue("--column").replace("px", "").trim() || "800";
    return WIDTHS.find(([k]) => k === w) ?? WIDTHS[1];
  };

  const buttons = () => {
    const head = document.querySelector(".site.top, .site-head");
    if (!head || head.querySelector(".prefs")) return;
    const box = document.createElement("span");
    box.className = "prefs";
    const button = (cls) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `pref ${cls}`;
      box.append(b);
      return b;
    };
    const cols = button("column");
    const showColumn = () => {
      const [w, name] = current();
      cols.textContent = w;
      cols.setAttribute("aria-label", `Column width: ${name} (${w}px)`);
    };
    cols.onclick = () => {
      const at = WIDTHS.indexOf(current());
      const [w] = WIDTHS[(at + 1) % WIDTHS.length];
      root.style.setProperty("--column", w === "800" ? "" : `${w}px`);
      put(COLUMN, w === "800" ? null : w);
      showColumn();
    };
    // A toggle: its name stays "Dark theme", pressed while the page is dark
    const mode = button("theme");
    mode.setAttribute("aria-label", "Dark theme");
    const showTheme = () => mode.setAttribute("aria-pressed", String(isDark()));
    mode.onclick = () => {
      const next = isDark() ? "light" : "dark";
      root.dataset.theme = next;
      put(THEME, next);
      showTheme();
    };
    showColumn();
    showTheme();
    head.append(box);
  };
  // Deferred, the page is parsed by now; async (or loaded early), wait for it
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", buttons);
  else buttons();
})();
