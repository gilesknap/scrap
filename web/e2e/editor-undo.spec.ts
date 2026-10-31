// The editor's Undo key (#313): the browser's own undo, for phones whose keyboard has none.
// It takes back typing and the editor's keys in order, is off until there is something to
// take back, and the six keys fit on one line on any phone.
import { expect, type Page, test } from "@playwright/test";

const open = async (page: Page) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  return {
    text: page.getByPlaceholder("Note or link"),
    key: (name: string) => page.locator(".editor .keys").getByRole("button", { name }),
  };
};

test("Undo takes back the keys and the typing, in order; off with nothing to undo", async ({
  page,
}) => {
  const { text, key } = await open(page);
  const undo = key("Undo");
  await expect(undo).toBeVisible();
  await expect(undo).toBeDisabled(); // a fresh editor: nothing to undo
  expect(await undo.evaluate((b) => b.getBoundingClientRect().height)).toBeGreaterThanOrEqual(48);

  // Typed as a phone's keyboard commits a word: one insert, so one step to take back (key by
  // key, as Playwright presses them, Chrome keeps a step a letter)
  await text.focus();
  await page.keyboard.insertText("milk");
  await expect(undo).toBeEnabled();
  await key("Bullet: make the line a bullet").click();
  await expect(text).toHaveValue("- milk");
  await undo.click();
  await expect(text).toHaveValue("milk"); // the Bullet first
  await undo.click();
  await expect(text).toHaveValue(""); // then the typing
  await expect(undo).toBeDisabled(); // back to how it opened
  await expect(text).toBeFocused(); // the keyboard stays up

  // Not while previewed, as the other keys
  await text.fill("milk");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(undo).toBeHidden();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(undo).toBeVisible();

  // Cancelled, the next editor starts with it off again
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  await page.getByRole("button", { name: "Note" }).click();
  await expect(key("Undo")).toBeDisabled();
});

// At 100% text the words go under about 356 px (css/composer.css): icons alone at 320 px
for (const [width, words] of [
  [320, false],
  [360, true],
  [390, true],
  [430, true],
] as const) {
  test(`the six keys fit on one line at ${width} px, ${words ? "each word on one line" : "icons alone"}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 640 });
    await open(page);
    await expect(page.locator(".editor .keys button")).toHaveCount(6);
    await expect
      .poll(
        () =>
          page.evaluate(() => {
            const row = document.querySelector(".editor .keys") as HTMLElement;
            const keys = [...row.querySelectorAll("button")];
            const top = keys[0]?.getBoundingClientRect().y;
            const bad = keys.filter((b) => {
              const r = b.getBoundingClientRect();
              const word = (b.querySelector("span") as HTMLElement).getClientRects();
              const w = word[0];
              return (
                r.x < 0 ||
                r.right > innerWidth ||
                r.y !== top ||
                r.height < 48 ||
                word.length > 1 || // wrapped
                (w && (w.left < r.left || w.right > r.right)) // wider than its key
              );
            });
            return {
              overflow: document.documentElement.scrollWidth > innerWidth,
              rowOverflow: row.scrollWidth > row.clientWidth,
              words: keys.map((b) => (b.querySelector("span") as HTMLElement).offsetWidth > 0),
              bad: bad.map((b) => b.textContent),
            };
          }),
        { message: `no overflow at ${width} px` },
      )
      .toEqual({ overflow: false, rowOverflow: false, words: Array(6).fill(words), bad: [] });
  });
}
