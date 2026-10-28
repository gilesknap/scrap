// Readout for a phone test copy (sim/phone.sh), bottom left, live: the root text size, the kept
// text size choice, the zoom (dpr) and width, and whether it runs installed or in a tab. Also
// registers a pass-through service worker so Chrome offers Install.
(() => {
  const el = document.createElement("div");
  el.style.cssText =
    "position:fixed;left:4px;bottom:4px;z-index:99;font:11px/1.2 monospace;background:#000c;color:#ff0;padding:2px 4px;border-radius:4px;pointer-events:none";
  const show = () => {
    const kept = localStorage.getItem("scrap.text_size");
    const mode = matchMedia("(display-mode: standalone)").matches ? "installed" : "tab";
    el.textContent = `root ${getComputedStyle(document.documentElement).fontSize} · kept ${kept ?? "none"} · dpr ${devicePixelRatio.toFixed(2)} · w ${innerWidth} · ${mode}`;
  };
  addEventListener("DOMContentLoaded", () => {
    document.body.append(el);
    show();
    setInterval(show, 1000);
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("./test-sw.js");
})();
