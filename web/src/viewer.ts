// Full-screen photo viewer: opens fitted; pinch, wheel or double-tap to zoom, drag to pan,
// swipe or arrows between photos. The phone's Back button closes it (a history entry).
import { type Icon, icon } from "./icons";
import { download, h, share } from "./ui";
import { clamp, type Fingers, fitView, pinch, type View, zoomTo } from "./zoom";

export interface Photo {
  src: string; // what is shown
  save: string; // the original, as a download
  name: string;
  share: [string, string, string]; // the file to share: address, name, type
}

type Pt = { x: number; y: number };

/** link: the page's address, which Share offers beside the photo. */
export function viewer(photos: Photo[], start: number, link?: string) {
  let i = start;
  let v: View = { s: 1, x: 0, y: 0 };
  let min = 1;
  const img = h("img", { alt: "", draggable: false });
  const box = () => ({ w: stage.clientWidth, h: stage.clientHeight });
  const size = () => ({ w: img.naturalWidth || 1, h: img.naturalHeight || 1 });
  const actual = () => Math.max(1 / devicePixelRatio, min); // one image pixel a device pixel
  const max = () => Math.max(actual(), min) * 4;
  const draw = (animate = false) => {
    img.classList.toggle("anim", animate);
    img.style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.s})`;
  };
  const set = (next: View, animate = false) => {
    v = clamp(next, size(), box(), min, max());
    draw(animate);
  };
  const toFit = (animate = true) => {
    v = fitView(size(), box());
    min = v.s;
    draw(animate);
  };
  const zoom = (s: number, p: Pt, animate = false) =>
    set(zoomTo(v, Math.min(Math.max(s, min), max()), p.x, p.y), animate);
  const centre = () => ({ x: box().w / 2, y: box().h / 2 });

  const note = h("p", { className: "note", hidden: true }, "No preview of this one: use Download");
  const stage = h("div", { className: "stage" }, img, note);
  const count = h("span", { className: "count" });
  let save = download("");
  const tool = (
    glyph: Icon | null,
    label: string,
    onclick: () => void,
    name = "",
    className = "",
  ) =>
    h(
      "button",
      { type: "button", onclick, className, ...(name && { "aria-label": name }) },
      glyph ? icon(glyph) : h("b", { "aria-hidden": "true" }, "1:1"),
      !name && label,
    );
  const prev = tool("back", "", () => show(i - 1), "Previous photo", "step");
  const next = tool("next", "", () => show(i + 1), "Next photo", "step");
  const close = tool("close", "", () => history.back(), "Close", "close");
  const bar = h(
    "div",
    { className: "tools" },
    tool("fit", "Fit", () => toFit()),
    tool(null, "100%", () => zoom(actual(), centre(), true)),
    save,
    share(() => ({ title: photos[i].name, file: photos[i].share }), link, ["image", "Photo"]),
  );
  const root = h(
    "div",
    { className: "viewer", role: "dialog", "aria-modal": "true", "aria-label": "Photo" },
    stage,
    bar,
    count,
    close,
  );
  if (photos.length > 1) root.append(prev, next);

  function show(n: number) {
    i = (n + photos.length) % photos.length;
    const p = photos[i];
    img.alt = p.name;
    const fresh = download(p.save);
    save.replaceWith(fresh);
    save = fresh;
    count.textContent = photos.length > 1 ? `${i + 1} / ${photos.length}` : "";
    img.style.visibility = "hidden";
    note.hidden = true;
    img.onload = () => {
      toFit(false);
      img.style.visibility = "";
    };
    img.onerror = () => {
      note.hidden = false; // e.g. a format the server can't preview
    };
    img.src = p.src;
  }

  // Pointers: one drags (or swipes when fitted), two pinch; a quick second tap toggles zoom.
  const down = new Map<number, Pt>();
  let gesture: Fingers | null = null;
  let start0: (Pt & { t: number; moved: boolean }) | null = null;
  let lastTap: (Pt & { t: number }) | null = null;
  const local = (e: PointerEvent) => {
    const r = stage.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const spread = () => {
    const [a, b] = [...down.values()];
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) || 1 };
  };
  stage.onpointerdown = (e) => {
    stage.setPointerCapture(e.pointerId);
    down.set(e.pointerId, local(e));
    if (down.size === 1) start0 = { ...local(e), t: e.timeStamp, moved: false };
    if (down.size === 2) gesture = spread();
  };
  stage.onpointermove = (e) => {
    const was = down.get(e.pointerId);
    if (!was) return;
    const p = local(e);
    down.set(e.pointerId, p);
    if (start0 && Math.hypot(p.x - start0.x, p.y - start0.y) > 10) start0.moved = true;
    if (down.size === 2 && gesture) {
      const now = spread();
      set(pinch(v, gesture, now, min, max()));
      gesture = now;
    } else if (down.size === 1 && v.s > min * 1.01) {
      set({ s: v.s, x: v.x + p.x - was.x, y: v.y + p.y - was.y });
    }
  };
  const up = (e: PointerEvent) => {
    if (!down.delete(e.pointerId)) return;
    gesture = down.size === 2 ? spread() : null;
    if (down.size || !start0) return;
    const p = local(e);
    const dx = p.x - start0.x;
    const fitted = v.s <= min * 1.01;
    if (!start0.moved && e.timeStamp - start0.t < 300) {
      if (
        lastTap &&
        e.timeStamp - lastTap.t < 350 &&
        Math.hypot(p.x - lastTap.x, p.y - lastTap.y) < 40
      ) {
        lastTap = null;
        if (fitted) zoom(actual() > min * 1.2 ? actual() : min * 2.5, p, true);
        else toFit();
      } else lastTap = { ...p, t: e.timeStamp };
    } else if (
      fitted &&
      photos.length > 1 &&
      Math.abs(dx) > 60 &&
      Math.abs(dx) > Math.abs(p.y - start0.y)
    ) {
      show(i + (dx < 0 ? 1 : -1));
    }
    start0 = null;
  };
  stage.onpointerup = up;
  stage.onpointercancel = up;
  stage.onwheel = (e) => {
    e.preventDefault();
    zoom(v.s * Math.exp(-e.deltaY / 300), local(e as unknown as PointerEvent));
  };

  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape") history.back();
    else if (e.key === "ArrowLeft") show(i - 1);
    else if (e.key === "ArrowRight") show(i + 1);
  };
  const resize = () => (v.s <= min * 1.01 ? toFit(false) : set(v));
  // Back closes the viewer; this runs before the router's listener, which it stops.
  const back = (e: PopStateEvent) => {
    e.stopImmediatePropagation();
    root.remove();
    removeEventListener("popstate", back, true);
    removeEventListener("keydown", keys);
    removeEventListener("resize", resize);
    document.body.classList.remove("viewing");
    opener?.focus();
  };
  const opener = document.activeElement as HTMLElement | null;
  history.pushState({ viewer: true }, "");
  addEventListener("popstate", back, true);
  addEventListener("keydown", keys);
  addEventListener("resize", resize);
  document.body.classList.add("viewing");
  document.body.append(root);
  show(i);
  close.focus();
}
