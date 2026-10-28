// The chosen app theme before first paint (theme.ts keeps it up to date). A file rather than
// an inline script, so the page's Content-Security-Policy can say script-src 'self'.
try {
  const t = localStorage.getItem("scrap.theme");
  if (t === "light" || t === "dark") {
    document.documentElement.dataset.theme = t;
    for (const m of document.querySelectorAll('meta[name="theme-color"]'))
      m.content = t === "dark" ? "#161411" : "#f6f3ec";
  }
  // and the chosen text size (textsize.ts), so the first paint is at it
  const s = Number(localStorage.getItem("scrap.text_size"));
  if (s >= 0.8 && s <= 1.3) {
    document.documentElement.style.fontSize = `${17 * s}px`;
    document.documentElement.dataset.text = String(s); // main.ts then leaves it
  }
} catch {}
