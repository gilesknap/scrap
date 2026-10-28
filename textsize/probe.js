// Test readout, bottom left: the root text size and the kept choice, live.
(() => {
  const el = document.createElement("div");
  el.style.cssText = "position:fixed;left:4px;bottom:4px;z-index:99;font:11px/1.2 monospace;background:#000c;color:#ff0;padding:2px 4px;border-radius:4px;pointer-events:none";
  const show = () => {
    const s = localStorage.getItem("scrap.text_size");
    el.textContent = `root ${getComputedStyle(document.documentElement).fontSize} · kept ${s ?? "none (100%)"} · ${matchMedia("(display-mode: standalone)").matches ? "installed" : "tab"}`;
  };
  addEventListener("DOMContentLoaded", () => { document.body.append(el); show(); setInterval(show, 1000); });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("./test-sw.js");
})();
