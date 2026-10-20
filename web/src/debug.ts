// DEBUG AID, off by default: a small panel of viewport numbers for a real phone, where the
// on-screen keyboard behaves unlike any emulator. Tap the build id at the bottom of the search
// screen five times to turn it on or off (kept in localStorage).
const KEY = "scrap.debug";
let taps = 0;

export function tapBuild() {
  if (++taps < 5) return;
  taps = 0;
  localStorage.setItem(KEY, localStorage.getItem(KEY) === "1" ? "0" : "1");
  location.reload();
}

export function debugPanel() {
  if (localStorage.getItem(KEY) !== "1") return;
  const el = document.createElement("pre");
  el.className = "debug";
  const vv = window.visualViewport;
  const show = () => {
    const bar = document.querySelector(".editor > .bar")?.getBoundingClientRect();
    const r = (n?: number) => (n === undefined ? "-" : Math.round(n));
    el.textContent = [
      `inner ${innerWidth}x${innerHeight} dpr ${devicePixelRatio}`,
      `vv h ${r(vv?.height)} top ${r(vv?.offsetTop)} pageTop ${r(vv?.pageTop)} scale ${vv?.scale.toFixed(2)}`,
      `scrollTop ${document.scrollingElement?.scrollTop}`,
      `editor bar ${bar ? `top ${r(bar.top)} bottom ${r(bar.bottom)}` : "closed"}`,
      `mode ${matchMedia("(display-mode: standalone)").matches ? "standalone" : "browser"}`,
      `meta ${document.querySelector('meta[name="viewport"]')?.getAttribute("content")}`,
      navigator.userAgent,
    ].join("\n");
  };
  for (const e of ["resize", "scroll"]) vv?.addEventListener(e, show);
  for (const e of ["focusin", "focusout", "scroll", "resize"]) addEventListener(e, show, true);
  setInterval(show, 1000);
  show();
  document.body.append(el);
}
