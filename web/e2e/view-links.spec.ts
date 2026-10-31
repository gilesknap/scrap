// Following a link from one page to another (#288): the phone's Back (history back, one step)
// returns to the linking page, and Delete there goes back to it with Undo. Opened cold, the
// top bar's Back and Delete go where Back names, staying in the app. A full address on another
// of the server's addresses (SCRAP_PUBLIC_URL, playwright.config.ts) opens in place too (#290).
import { expect, type Page, test } from "@playwright/test";
import { capture, ulid } from "./helpers";

const make = (page: Page, text: string, kind = "note") => capture(page, text, { kind });

const title = (page: Page) => page.locator(".page h1");
const LAN = "http://scrap-lan.example:8000"; // in SCRAP_PUBLIC_URL (playwright.config.ts)

/** A todo A linking to a note B, by [[slug]], by its full address (as a model writes it) and by
 * its address on another of the server's addresses, opened from the search screen. */
async function linked(page: Page, baseURL: string) {
  const tag = ulid().slice(-6);
  const b = await make(page, `Linked B ${tag}`);
  const a = await make(
    page,
    `Linking A ${tag}\n\n- [ ] [[${b.slug}|by slug]]\n- [ ] [by address](${baseURL}/p/${b.slug})\n- [ ] [by LAN](${LAN}/p/${b.slug})`,
    "todo",
  );
  await page.goto(`/search?q=${encodeURIComponent(`Linking A ${tag}`)}`);
  await page.locator(".hits a", { hasText: `Linking A ${tag}` }).click();
  await expect(title(page)).toHaveText(`Linking A ${tag}`);
  return { a, b, tag };
}

for (const how of ["by slug", "by address", "by LAN"]) {
  test(`a link ${how} from page A to B: the phone's Back returns to A`, async ({
    page,
    baseURL,
  }) => {
    const { a, b, tag } = await linked(page, baseURL as string);
    const link = page.locator(".page .body a", { hasText: how });
    await expect(link).toHaveAttribute("href", `/p/${b.slug}`);
    await expect(link).not.toHaveAttribute("target", /.*/); // not a new window
    const pages = page.context().pages().length;
    await link.click();
    await expect(page).toHaveURL(`/p/${b.slug}`);
    await expect(title(page)).toHaveText(`Linked B ${tag}`);
    expect(page.context().pages().length).toBe(pages); // opened in place
    await page.goBack(); // the phone's Back gesture
    await expect(page).toHaveURL(`/p/${a.slug}`);
    await expect(title(page)).toHaveText(`Linking A ${tag}`);
    // A's own Back goes to the list A was opened from, with no jump beside it
    await expect(page.locator("#backto")).toHaveText("Search");
    await expect(page.locator("#jump")).toBeHidden();
  });
}

test("Delete on B, opened from a link in A, lands back on A with Undo", async ({
  page,
  baseURL,
}) => {
  const { a, b, tag } = await linked(page, baseURL as string);
  await page.locator(".page .body a", { hasText: "by slug" }).click();
  await expect(title(page)).toHaveText(`Linked B ${tag}`);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(`/p/${a.slug}`); // not the search screen
  await expect(title(page)).toHaveText(`Linking A ${tag}`);
  await expect(page.getByText("Page deleted")).toBeVisible();
  expect((await page.request.get(`/api/pages/${b.slug}`)).status()).toBe(404);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page).toHaveURL(`/p/${b.slug}`);
  await expect(title(page)).toHaveText(`Linked B ${tag}`);
});

test("opened cold on B: Back and Delete go where Back names, staying in the app", async ({
  page,
}) => {
  const tag = ulid().slice(-6);
  const b = await make(page, `Cold B ${tag}`);
  await page.goto(`/p/${b.slug}`);
  await expect(page.locator("#backto")).toHaveText("Capture");
  await page.locator("#back").click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();

  const t = await make(page, `Cold todo ${tag}`, "todo");
  await page.goto(`/p/${t.slug}`);
  await expect(page.locator("#backto")).toHaveText("Todos");
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/todos$/);
  await expect(page.getByText("Page deleted")).toBeVisible();
});

/** A page with a file (as the page shows one: a row that opens it in a new window). */
async function withFile(page: Page) {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", `File page ${ulid().slice(-6)}`);
  form.append("file", new Blob(["Plain words"], { type: "text/plain" }), "words.txt");
  const ref = (await (await page.request.post("/api/captures", { multipart: form })).json()) as {
    slug: string;
  };
  await page.goto(`/p/${ref.slug}`);
  return ref;
}

test("Android's home-screen app: a file opens in place, and the phone's Back returns (#443)", async ({
  page,
}) => {
  // As Chrome installs it on Android (the Pixel 7's user agent): display-mode standalone
  await page.addInitScript(() => {
    const real = window.matchMedia.bind(window);
    window.matchMedia = (q: string) =>
      q.includes("display-mode: standalone")
        ? ({ ...real(q), matches: true } as MediaQueryList)
        : real(q);
  });
  const ref = await withFile(page);
  const link = page.locator(".page a.file").first();
  await expect(link).toHaveAttribute("target", "_blank"); // a new window elsewhere
  const pages = page.context().pages().length;
  await link.click();
  await expect(page).toHaveURL(/\/api\/blobs\/[0-9a-f]{64}$/);
  await expect(page.locator("body")).toContainText("Plain words");
  expect(page.context().pages().length).toBe(pages); // not a new window
  await page.goBack(); // the phone's Back gesture
  await expect(page).toHaveURL(`/p/${ref.slug}`);
  await expect(page.locator(".page a.file").first()).toBeVisible();
});

test("in a browser tab a file still opens in a new tab", async ({ page }) => {
  const ref = await withFile(page);
  const [popup] = await Promise.all([
    page.waitForEvent("popup"),
    page.locator(".page a.file").first().click(),
  ]);
  await expect(popup).toHaveURL(/\/api\/blobs\/[0-9a-f]{64}$/);
  await expect(page).toHaveURL(`/p/${ref.slug}`);
});
