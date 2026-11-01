// The questions public pages ask (#497): the warning before a page is made public (every time),
// and Refresh all's one question before pages go public for the first time. In-app dialogs, not
// confirm(): Cancel has focus, so Enter never publishes, and the amber button is the only one.
import type { FileRef, Page, PublicPage } from "./api";
import { h } from "./ui";
import "./css/publicpages.css";

/** The words of a question: its title, lines, a list, a quiet last line, and its OK button. */
export interface Question {
  title: string;
  lines: (string | Node)[][];
  list: string[];
  hint?: string;
  ok: string;
}

/** The page's files that are not images: they go public with it, by name. */
export const filesOf = (p: Page): FileRef[] => {
  const seen = new Set<string>();
  return p.captures
    .flatMap((c) => c.blobs)
    .filter((b) => !b.mime.startsWith("image/") && !seen.has(b.sha256) && seen.add(b.sha256));
};

/** What goes public with the page, a line each: its tags, Claude's write-up and summary, its
 * attached files by name. */
export function goesWith(p: Page): string[] {
  const files = filesOf(p).map((f) => f.filename || f.mime);
  return [
    ...(p.tags.length ? [`its tags: ${p.tags.map((t) => `#${t}`).join(" ")}`] : []),
    "Claude's write-up and summary",
    ...(files.length
      ? [`${files.length === 1 ? "its attached file" : "its attached files"}: ${files.join(", ")}`]
      : []),
  ];
}

/** The warning before a page goes public. */
export function warning(p: Page, host: string): Question {
  return {
    title: "Make this page public?",
    lines: [
      ["Anyone with the link can read it at ", h("b", {}, host), "."],
      ["It goes public with:"],
    ],
    list: goesWith(p),
    hint: "Links to private pages show their titles as plain text.",
    ok: "Make public",
  };
}

/** Refresh all's question, when some public pages have never been published. */
export const firstTime = (pages: PublicPage[]): Question => ({
  title: "Publish for the first time?",
  lines: [["These pages will go public for the first time:"]],
  list: pages.map((q) => q.title),
  ok: "OK",
});

/** Ask in a modal dialog: resolves true for OK, false for Cancel (or Escape, Back, or a tap
 * outside it). */
export function ask(q: Question): Promise<boolean> {
  const cancel = h("button", { type: "button" }, "Cancel");
  const ok = h("button", { type: "button", className: "primary" }, q.ok);
  const d = h(
    "dialog",
    { className: "pubask", "aria-labelledby": "pubask-h" },
    h("h2", { id: "pubask-h" }, q.title),
    ...q.lines.map((l) => h("p", {}, ...l)),
    q.list.length ? h("ul", {}, ...q.list.map((w) => h("li", { dir: "auto" }, w))) : "",
    q.hint ? h("p", { className: "hint" }, q.hint) : "",
    h("div", { className: "row" }, cancel, ok),
  );
  document.body.append(d);
  return new Promise((done) => {
    const end = (yes: boolean) => {
      d.close();
      d.remove();
      done(yes);
    };
    cancel.onclick = () => end(false);
    ok.onclick = () => end(true);
    d.addEventListener("cancel", (e) => {
      e.preventDefault(); // Escape: closed here, as Cancel
      end(false);
    });
    d.addEventListener("click", (e) => e.target === d && end(false)); // the backdrop
    // Its keys are its own: not Settings' (Escape there closes the sheet, Tab keeps to it)
    d.addEventListener("keydown", (e) => e.stopPropagation());
    d.showModal();
    cancel.focus(); // the safe choice has focus
  });
}
