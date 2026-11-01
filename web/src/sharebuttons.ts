// Share and Download are drawn here (out of the app shell: a page and the photo viewer use
// them); what they do is in sharing.ts, a chunk loaded on the first tap.
import { type Icon, icon } from "./icons";
import { h, toast } from "./ui";

const sharing = () => import("./sharing");
const later = (job: (m: typeof import("./sharing")) => unknown) =>
  void sharing().then(job, () => toast("Can't do that offline: reload scrap and try again"));

/** A Download link that fetches the file itself (sharing.ts), so it can say it is busy and
 * when the file is saved or why not. */
export function download(href: string, className = "button"): HTMLAnchorElement {
  const a = h("a", { href, className, download: "" }, icon("download"), "Download");
  a.onclick = (e) => {
    e.preventDefault();
    later((m) => m.download(a, href));
  };
  return a;
}

/** A Share button to send text, or a file from the server, to another app; none where
 * the phone can't share. Given the page's link, Share first asks which: **Link** (the
 * address, nothing fetched) or the content (`content`: its icon and word), then `more` (a
 * page's Download) if given. Given `more`, a computer with no share sheet (a mouse) has the
 * menu too: it copies, prints and downloads (sharing.ts). */
export function share(
  what: () => { title: string; text?: string; file?: string[] },
  link?: string,
  content: [Icon, string] = ["note", "Text"],
  more?: HTMLElement[],
) {
  if (!navigator.share && !(more && matchMedia("(pointer: fine)").matches)) return null;
  const b = h("button", { type: "button" }, icon("share"), "Share");
  // The first tap loads sharing.ts, which takes the button's taps from then on
  const first = (e: MouseEvent) => {
    b.onclick = null; // a second tap meanwhile: nothing twice
    void sharing().then(
      (m) => m.attach(b, { what, link, content, more })(e),
      () => {
        b.onclick = first;
        toast("Can't do that offline: reload scrap and try again");
      },
    );
  };
  b.onclick = first;
  return b;
}
