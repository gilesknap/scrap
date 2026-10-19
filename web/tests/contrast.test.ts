// The design system's text/background pairs meet WCAG AA in both themes (4.5:1 for text, 3:1
// for control edges), read straight from src/tokens.css.
import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

const css = readFileSync(new URL("../src/tokens.css", import.meta.url), "utf8");

function tokens(block: string): Record<string, string> {
  return Object.fromEntries(
    [...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2]]),
  );
}
const light = tokens(css.split("@media")[0]);
const dark = { ...light, ...tokens(css.split("prefers-color-scheme: dark")[1].split("@media")[0]) };

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5]
    .map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// [foreground, background, minimum]
const PAIRS: [string, string, number][] = [
  ...["bg", "surface", "sunk"].flatMap((bg): [string, string, number][] => [
    ["ink", bg, 4.5],
    ["ink-2", bg, 4.5],
    ["accent-ink", bg, 4.5],
    ["danger", bg, 4.5],
  ]),
  ["ink-3", "bg", 4.5],
  ["ink-3", "surface", 4.5],
  ["on-accent", "accent", 4.5],
  ["ink", "accent-soft", 4.5],
  ["accent-ink", "accent-soft", 4.5],
  ["danger", "danger-soft", 4.5],
  ["ink", "danger-soft", 4.5],
  ["ink-2", "danger-soft", 4.5],
  ["on-toast", "toast", 4.5],
  ["toast-action", "toast", 4.5],
  ["line-strong", "bg", 3],
  ["line-strong", "surface", 3],
];

// And every rule in style.css that sets both a text colour and a background from tokens. Text
// that inherits its colour onto another element's background is covered by PAIRS above and,
// on the real pixels, by the computed-colour sweep in e2e/view.spec.ts.
const style = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const DRAWN: [string, string, number][] = [];
for (const [, body] of style.matchAll(/[^{}]+\{([^{}]*)\}/g)) {
  const fg = body.match(/(?:^|[\s;])color:\s*var\(--([\w-]+)\)/)?.[1];
  const bg = body.match(/background(?:-color)?:\s*var\(--([\w-]+)\)/)?.[1];
  if (fg && bg && light[fg] && light[bg]) DRAWN.push([fg, bg, 4.5]);
}

describe.each([
  ["light", light],
  ["dark", dark],
])("%s theme", (_, t) => {
  test.each(PAIRS)("%s on %s is at least %d:1", (fg, bg, min) => {
    expect(t[fg], fg).toBeDefined();
    expect(t[bg], bg).toBeDefined();
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(min);
  });
  test.each(DRAWN)("a style.css rule sets %s on %s: at least %d:1", (fg, bg, min) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(min);
  });
});

test("style.css rules set some token pairs", () => {
  expect(DRAWN.length).toBeGreaterThan(5);
});

test("text over a photo (viewer count, tools) stays readable on a white photo", () => {
  const m = css.match(/--overlay:\s*rgb\((\d+) (\d+) (\d+) \/ (\d+)%\)/);
  expect(m).toBeTruthy();
  const [r, g, b, a] = (m as RegExpMatchArray).slice(1).map(Number);
  const over = (c: number) => Math.round((c * a) / 100 + 255 * (1 - a / 100));
  const hex = `#${[r, g, b].map((c) => over(c).toString(16).padStart(2, "0")).join("")}`;
  expect(contrast(light["on-overlay"], hex)).toBeGreaterThanOrEqual(4.5);
});
