// The editor's Undo key (#313): the browser's own undo, for phones whose keyboard has none.
// It takes back typing and the editor's keys in order, is off until there is something to
// take back, and the six keys fit on one line on any phone.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

const keyIn = (page: Page) => (name: string) =>
  page.locator(".editor .keys").getByRole("button", { name });

const open = async (page: Page) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  return {
    text: page.getByPlaceholder("Note or link"),
    key: keyIn(page),
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

test("the history is the page's: after typing a tag, Undo is off until the text is typed in", async ({
  page,
}) => {
  const { text, key } = await open(page);
  const undo = key("Undo");
  await text.focus();
  await page.keyboard.insertText("milk");
  await expect(undo).toBeEnabled();
  await page.locator(".editor .fold > summary", { hasText: "Tags" }).click();
  const tag = page.getByRole("textbox", { name: "Add a tag" });
  await tag.focus();
  await page.keyboard.insertText("dairy");
  await expect(undo).toBeDisabled(); // an undo now would take back the tag, not the text
  await expect(text).toHaveValue("milk");
  await text.focus();
  await page.keyboard.insertText(" and eggs");
  await expect(undo).toBeEnabled();
  await undo.click();
  await expect(text).toHaveValue("milk");
  await expect(tag).toHaveValue("dairy");
});

test("a file added takes its place in the history: Undo takes it out", async ({ page }) => {
  const { text, key } = await open(page);
  await text.focus();
  await page.keyboard.insertText("minutes");
  const chooser = page.waitForEvent("filechooser");
  await page.locator(".editor").getByRole("button", { name: "File", exact: true }).click();
  await (await chooser).setFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("some notes"),
  });
  await expect(text).toHaveValue("minutes\n\n⟦file 1: notes.txt⟧\n\n");
  await expect(page.locator(".editor .embeds .embed")).toHaveCount(1);
  await key("Undo").click();
  await expect(text).toHaveValue("minutes");
  await expect(page.locator(".editor .embeds .embed")).toHaveCount(0);
  await key("Undo").click();
  await expect(text).toHaveValue("");
  await expect(key("Undo")).toBeDisabled();
});

test("in a page's editor: off as it opens, as a draft comes back, and after Discard it", async ({
  page,
}) => {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text: `Undo page ${ulid().slice(-6)}\n\nfirst line` },
  });
  const { slug } = (await r.json()) as { slug: string };
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const body = page.getByLabel("Body");
  const key = keyIn(page);
  await expect(key("Undo")).toBeDisabled();
  const opened = await body.inputValue();

  // Typed in the body: on; typed in the title: off, the body as it was
  await body.focus();
  await body.press("ControlOrMeta+End");
  await page.keyboard.insertText(" more");
  await expect(key("Undo")).toBeEnabled();
  await page.getByLabel("Title").focus();
  await page.keyboard.insertText("!");
  await expect(key("Undo")).toBeDisabled();
  await expect(body).toHaveValue(`${opened} more`);

  // Left by Back and opened again as the draft: nothing to undo
  await page.goBack();
  await expect(page.locator(".editor")).toBeHidden();
  await page.reload();
  await page.getByRole("button", { name: "Edit draft (unsaved)" }).click();
  await expect(body).toHaveValue(`${opened} more`);
  await expect(key("Undo")).toBeDisabled();
  await body.focus();
  await page.keyboard.insertText("x");
  await expect(key("Undo")).toBeEnabled();

  // Discard it puts the page's text back, as code: no history to undo
  await page.getByRole("button", { name: "Discard it" }).click();
  await expect(body).toHaveValue(opened);
  await expect(key("Undo")).toBeDisabled();
});

test("at a larger text size the words go sooner: icons alone at 390 px and 130%", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("scrap.text_size", "1.3"));
  await page.setViewportSize({ width: 390, height: 640 });
  await open(page);
  const keys = page.locator(".editor .keys button");
  await expect(keys).toHaveCount(6);
  await expect
    .poll(() =>
      keys.evaluateAll((ks) => ({
        words: ks.filter((k) => (k.querySelector("span") as HTMLElement).offsetWidth > 0).length,
        fit: ks.every((k) => k.getBoundingClientRect().right <= innerWidth),
        overflow: document.documentElement.scrollWidth > innerWidth,
      })),
    )
    .toEqual({ words: 0, fit: true, overflow: false });
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
