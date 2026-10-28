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
// and the chosen text size (textsize.ts, whose list of values this is), so the first paint is at
// it; a value that is not one of them is the phone's. 17 px is css/base.css's root.
try {
  const s = localStorage.getItem("scrap.text_size");
  if (["0.8", "0.9", "1", "1.15", "1.3"].includes(s)) {
    document.documentElement.style.fontSize = `${17 * Number(s)}px`;
    document.documentElement.dataset.text = s; // main.ts then leaves it
  }
} catch {}
