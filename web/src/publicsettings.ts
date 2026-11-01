// Settings → Public pages (#497): Refresh N pages, which draws every public page again and
// publishes it (publicpages.ts, loaded on the tap), for what the PWA did not see: edits over
// MCP, a new write-up, a new scrap. It says how far it has got, then when it was done.
import type { PublicPage } from "./api";
import { publicPages, whyNot } from "./publicapi";
import { h } from "./ui";

const pagesWord = (n: number) => (n === 1 ? "1 page" : `${n} pages`);
export const NONE = "No pages are public. Make one public from its Share menu.";
const WHAT =
  "For changes made elsewhere (over MCP, a new write-up, a new scrap): draws each public page again and publishes it.";

/** The section's parts: its label, the button and its hint. */
export function publicSection(): HTMLElement[] {
  const button = h("button", { type: "button", className: "button", hidden: true }, "Refresh");
  const hint = h("p", { className: "hint" });
  const say = (list: PublicPage[] | null, done = "") => {
    const n = list?.length ?? 0;
    button.hidden = !n;
    button.textContent = `Refresh ${pagesWord(n)}`;
    hint.textContent = list === null ? "Can't reach the server." : n ? `${done}${WHAT}` : NONE;
  };
  const load = (done = "") =>
    publicPages().then(
      (l) => say(l, done),
      () => say(null),
    );
  void load();
  button.onclick = async () => {
    if (button.getAttribute("aria-busy") === "true") return;
    button.setAttribute("aria-busy", "true");
    try {
      const m = await import("./publicpages");
      const out = await m.refreshAll((i, n) => {
        button.textContent = `Refreshing ${i} of ${n}…`;
      });
      if (!out) return void (await load()); // cancelled
      const at = new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
      const failed = out.failed.length ? ` Not refreshed: ${out.failed.join(", ")}.` : "";
      await load(`Refreshed ${pagesWord(out.done)} at ${at}.${failed} `);
    } catch (err) {
      await load(`Not refreshed: ${whyNot(err)}. `);
    } finally {
      button.removeAttribute("aria-busy");
    }
  };
  return [h("h3", { className: "label" }, "Public pages"), button, hint];
}
