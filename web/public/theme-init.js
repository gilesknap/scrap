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
