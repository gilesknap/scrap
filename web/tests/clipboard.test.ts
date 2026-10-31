import { afterEach, describe, expect, it, vi } from "vitest";
import { copyRich, copyText } from "../src/clipboard";
import { toast } from "../src/ui";

vi.mock("../src/ui", async (orig) => ({ ...(await orig<object>()), toast: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(toast).mockClear();
});

describe("copyText", () => {
  it("puts the text on the clipboard and says what was copied", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await copyText("https://x/p/a", "Link");
    expect(writeText).toHaveBeenCalledWith("https://x/p/a");
    expect(toast).toHaveBeenCalledWith("Link copied");
  });

  it("fails, saying why, where there is no clipboard (not a secure page)", async () => {
    vi.stubGlobal("navigator", {});
    await expect(copyText("x", "Link")).rejects.toThrow("can't copy");
    expect(toast).not.toHaveBeenCalled();
  });
});

describe("copyRich", () => {
  it("writes the html and the plain text as one item, within the call", async () => {
    const made: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "ClipboardItem",
      class {
        constructor(data: Record<string, unknown>) {
          made.push(data);
        }
      },
    );
    const write = vi.fn(async () => {});
    vi.stubGlobal("navigator", { clipboard: { write, writeText: vi.fn() } });
    await copyRich(async () => "<h1>Hi</h1>", "# Hi");
    expect(write).toHaveBeenCalledOnce();
    const [item] = made;
    expect(Object.keys(item)).toEqual(["text/html", "text/plain"]);
    const html = await (item["text/html"] as Promise<Blob>);
    expect([html.type, await html.text()]).toEqual(["text/html", "<h1>Hi</h1>"]);
    const text = item["text/plain"] as Blob;
    expect([text.type, await text.text()]).toEqual(["text/plain", "# Hi"]);
    expect(toast).toHaveBeenCalledWith("Rich text copied");
  });

  it("copies the plain text where the browser has no ClipboardItem, making no html", async () => {
    vi.stubGlobal("ClipboardItem", undefined);
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const html = vi.fn(async () => "<p>x</p>");
    await copyRich(html, "# Hi");
    expect(writeText).toHaveBeenCalledWith("# Hi");
    expect(html).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("Text copied");
  });
});
