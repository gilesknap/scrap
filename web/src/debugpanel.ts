// DEBUG AID (debug.ts): the panel of viewport numbers, a chunk loaded only while it is on.
// It imports nothing, so loading it changes nothing in the app shell.
export function debugPanel() {
  const el = document.createElement("pre");
  el.className = "debug";
  const vv = window.visualViewport;
  const show = () => {
    const bar = document.querySelector(".editor > .bar")?.getBoundingClientRect();
    const r = (n?: number) => (n === undefined ? "-" : Math.round(n));
    el.textContent = [
      `inner ${innerWidth}x${innerHeight} dpr ${devicePixelRatio} screen ${screen.width}x${screen.height}`,
      // The text size the page got: 17 px unless the phone's setting reached it (iOS sets it)
      `root ${getComputedStyle(document.documentElement).fontSize} body ${getComputedStyle(document.body).fontSize}`,
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
