// Helpers for the specs: the search screen's Filters panel and the editor's folds.
import { expect, type Locator, type Page } from "@playwright/test";

/** The slider at the search box's end ("Filters", or "Filters, 2 on"). */
export const filtersButton = (page: Page) =>
  page.locator(".field-search").getByRole("button", { name: /^Filters/ });

/** Open the Filters panel, in place under the box (it may be open already), and its Arrange
 * fold (Order and Group, folded to one line) unless arrange is false. */
export async function filters(page: Page, arrange = true) {
  const button = filtersButton(page);
  await expect(button).toHaveAttribute("aria-expanded", /^(true|false)$/); // refine.ts is here
  if ((await button.getAttribute("aria-expanded")) !== "true") await button.click();
  const panel = page.locator("#fpanel");
  await expect(panel).toBeVisible();
  const fold = panel.locator("details.farrange");
  if (arrange && !(await fold.evaluate((d) => (d as HTMLDetailsElement).open)))
    await fold.locator("> summary").click();
  return panel;
}

/** Open a fold of the composer or editor ("Tags", "Due"), if it is folded. */
export async function openFold(scope: Locator, name: "Tags" | "Due") {
  const summary = scope.locator("details.fold > summary", { hasText: new RegExp(`^${name}`) });
  if (!(await summary.evaluate((s) => (s.parentElement as HTMLDetailsElement).open)))
    await summary.click();
  return summary;
}
