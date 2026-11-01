// On a computer the Todos tab's count sits after the word, as a tab's count ("Todos 2"):
// desktop.css drops the phone badge's border, so its line must fill the pill for the digit
// to be centred in it (#545), and the pill is centred on the label's line. 100 % and 130 % text.
import { expect, test } from "@playwright/test";
import { capture, day, deletePages } from "./helpers";

const made: string[] = [];
test.beforeAll(async ({ request }) => {
  const page = { request } as Parameters<typeof capture>[0];
  for (const d of [0, -1])
    made.push((await capture(page, `Badge due ${d}`, { kind: "todo", due: day(d) })).page_id);
});
test.afterAll(({ request }) => deletePages(request, made));

test.use({
  viewport: { width: 1280, height: 800 },
  isMobile: false,
  hasTouch: false,
});

for (const size of ["1", "1.3"]) {
  test(`the Todos count is centred in its pill and on the label, at ${size} text`, async ({
    page,
  }) => {
    await page.addInitScript((s) => localStorage.setItem("scrap.text_size", s), size);
    await page.goto("/topics");
    await expect(page.locator('nav a[href="/todos"] .due-n')).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const { digit, pill } = await page.evaluate(() => {
      const el = document.querySelector('nav a[href="/todos"] .due-n') as HTMLElement;
      const mid = (r: DOMRect) => r.top + r.height / 2;
      const text = (n: Node) => {
        const r = document.createRange();
        r.selectNodeContents(n);
        return r.getBoundingClientRect();
      };
      const label = [...(el.parentElement as HTMLElement).childNodes].find(
        (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim(),
      ) as Text;
      const box = el.getBoundingClientRect();
      return {
        digit: mid(text(el)) - mid(box),
        pill: mid(box) - mid(text(label)),
      };
    });
    expect(Math.abs(digit), `digit ${digit} px from the pill's centre`).toBeLessThanOrEqual(1);
    expect(Math.abs(pill), `pill ${pill} px from the label's centre`).toBeLessThanOrEqual(1);
  });
}
