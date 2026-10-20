// The contrast sweep's check, shared by the specs: run in the page with page.evaluate.
/** Text whose computed colour, over what is computed behind it, is under WCAG AA. */
export function lowContrast(skip = "") {
  type C = [number, number, number, number];
  const parse = (c: string): C | null => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (m) {
      const p = m[1]
        .split(/[ ,/]+/)
        .filter(Boolean)
        .map(Number);
      return [p[0], p[1], p[2], p[3] ?? 1];
    }
    const s = c.match(/srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?/);
    return s ? [+s[1] * 255, +s[2] * 255, +s[3] * 255, s[4] === undefined ? 1 : +s[4]] : null;
  };
  const lum = (c: C) =>
    c
      .slice(0, 3)
      .map((v) => v / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
      .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
  const over = (top: C, under: C): C => [
    ...([0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])) as [
      number,
      number,
      number,
    ]),
    1,
  ];
  const behind = (el: Element): C | null => {
    const stack: C[] = [];
    for (let e: Element | null = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (e.tagName === "IMG" || (cs.backgroundImage !== "none" && !e.matches("html, body")))
        return null; // over a picture or a gradient: covered by the overlay token test
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) {
        stack.push(c);
        if (c[3] >= 1) break;
      }
    }
    return stack.reverse().reduce((base, c) => over(c, base), [255, 255, 255, 1] as C);
  };
  const bad: string[] = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement as Element;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (!n.textContent?.trim() || !r.width || !r.height || cs.visibility === "hidden") continue;
    if (cs.fontSize === "0px" || el.closest("[hidden], button:disabled, .debug")) continue;
    if (skip && el.closest(skip)) continue;
    const bg = behind(el);
    const fg0 = parse(cs.color);
    if (!bg || !fg0) continue;
    let alpha = fg0[3];
    for (let e: Element | null = el; e; e = e.parentElement) alpha *= +getComputedStyle(e).opacity;
    const fg = over([fg0[0], fg0[1], fg0[2], alpha], bg);
    const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const size = Number.parseFloat(cs.fontSize);
    const large = size >= 24 || (size >= 18.66 && +cs.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5))
      bad.push(
        `${el.tagName}.${el.className} "${n.textContent.trim().slice(0, 30)}" ${ratio.toFixed(2)}`,
      );
  }
  return bad;
}
