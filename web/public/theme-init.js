// The chosen app theme before first paint (theme.ts keeps it up to date). A file rather than
// an inline script, so the page's Content-Security-Policy can say script-src 'self'.
try {
  const t = localStorage.getItem("scrap.theme");
  if (t === "light" || t === "dark") {
    document.documentElement.dataset.theme = t;
    for (const m of document.querySelectorAll('meta[name="theme-color"]'))
      m.content = t === "dark" ? "#161411" : "#f6f3ec";
  }
} catch {}
// and the chosen text size (textsize.ts; main.ts does the same), so the first paint is at it: a
// percentage of css/base.css's 17 px, or "phone" (base.css then follows the phone's font size)
try {
  const s = localStorage.getItem("scrap.text_size") ?? "";
  const n = Number(s);
  document.documentElement.dataset.text = s;
  if (n >= 0.8 && n <= 1.3) document.documentElement.style.fontSize = `${17 * n}px`;
} catch {}
