// Live readout: what text size this page is given, and what the phone's text scale is.
const out = document.getElementById("out");
const probe = document.createElement("div");
probe.style.cssText = "position:absolute;visibility:hidden;width:calc(1000px * env(preferred-text-scale, 0))";
document.body.append(probe);
const show = () => {
  const root = getComputedStyle(document.documentElement).fontSize;
  const env = probe.getBoundingClientRect().width / 1000;
  const chrome = (navigator.userAgent.match(/Chrome\/(\d+)/) || [])[1] || "?";
  out.textContent = [
    `page:        ${document.title}`,
    `mode:        ${matchMedia("(display-mode: standalone)").matches ? "INSTALLED app" : "browser tab"}`,
    `root font:   ${root}   (16px = not scaled)`,
    `env scale:   ${env ? env.toFixed(2) : "not supported / 0"}`,
    `zoom:        dpr ${devicePixelRatio}, width ${innerWidth}px, vv scale ${visualViewport ? visualViewport.scale.toFixed(2) : "-"}`,
    `Chrome:      ${chrome}`,
    `updated:     ${new Date().toLocaleTimeString()}`,
  ].join("\n");
};
show();
setInterval(show, 1000);
