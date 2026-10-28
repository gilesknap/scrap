import { afterEach, describe, expect, it, vi } from "vitest";
import { sharePageFile, sharePageHtml, tapExpired } from "../src/sharing";
import { toast } from "../src/ui";

vi.mock("../src/ui", async (orig) => ({ ...(await orig<object>()), toast: vi.fn() }));

const denied = Object.assign(new Error("not allowed"), { name: "NotAllowedError" });

describe("tapExpired", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is true for a NotAllowedError once the tap's activation has expired", () => {
    vi.stubGlobal("navigator", { userActivation: { isActive: false } });
    expect(tapExpired(denied)).toBe(true);
  });

  it("is false while the activation is live: the error is a real one", () => {
    vi.stubGlobal("navigator", { userActivation: { isActive: true } });
    expect(tapExpired(denied)).toBe(false);
  });

  it("is false where the browser does not say", () => {
    vi.stubGlobal("navigator", {});
    expect(tapExpired(denied)).toBe(false);
  });

  it("is false for any other error", () => {
    vi.stubGlobal("navigator", { userActivation: { isActive: false } });
    expect(tapExpired(new TypeError("x"))).toBe(false);
  });
});

describe("sharePageFile", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.mocked(toast).mockClear();
  });
  const reply = (name: string, type: string) =>
    new Response("x", {
      headers: { "Content-Type": type, "Content-Disposition": `attachment; filename="${name}"` },
    });
  const phone = (canShare: (d: ShareData) => boolean) => {
    const share = vi.fn(async () => {});
    vi.stubGlobal("navigator", { share, canShare });
    return share;
  };

  it("shares the zip with its photos as previews", async () => {
    const share = phone(() => true);
    const fetched = vi.fn(async () => reply("p.zip", "application/zip"));
    vi.stubGlobal("fetch", fetched);
    const saved = vi.fn();
    await sharePageFile("/api/pages/a/download", "A page", saved);
    expect(fetched).toHaveBeenCalledWith("/api/pages/a/download?photos=preview");
    expect(share).toHaveBeenCalledOnce();
    expect(saved).not.toHaveBeenCalled();
  });

  it("falls back to the plain download, originals, where files can't be shared", async () => {
    const share = phone(() => false);
    const fetched = vi.fn(async () => reply("p.zip", "application/zip"));
    vi.stubGlobal("fetch", fetched);
    const saved = vi.fn();
    await sharePageFile("/api/pages/a/download", "A page", saved);
    expect(fetched).toHaveBeenCalledOnce();
    expect(fetched).toHaveBeenCalledWith("/api/pages/a/download");
    expect(share).not.toHaveBeenCalled();
    expect(saved.mock.calls[0][0].name).toBe("p.zip");
  });

  it("saves the zip, and says so, where Chrome refuses it with a live tap", async () => {
    const share = vi.fn(async () => Promise.reject(denied));
    vi.stubGlobal("navigator", { share, canShare: () => true, userActivation: { isActive: true } });
    const fetched = vi.fn(async () => reply("p.zip", "application/zip"));
    vi.stubGlobal("fetch", fetched);
    const saved = vi.fn();
    await sharePageFile("/api/pages/a/download", "A page", saved);
    expect(fetched).toHaveBeenLastCalledWith("/api/pages/a/download");
    expect(saved.mock.calls[0][0].name).toBe("p.zip");
    expect(toast).toHaveBeenCalledWith("This phone can't share a zip; saved it instead");
  });

  it("leaves an expired tap to its own Share offer, saving nothing", async () => {
    const share = vi.fn(async () => Promise.reject(denied));
    vi.stubGlobal("navigator", {
      share,
      canShare: () => true,
      userActivation: { isActive: false },
    });
    vi.stubGlobal("fetch", async () => reply("p.zip", "application/zip"));
    const saved = vi.fn();
    await sharePageFile("/api/pages/a/download", "A page", saved);
    expect(saved).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("Page ready", "Share", expect.any(Function), 30_000);
    expect(toast).not.toHaveBeenCalledWith("This phone can't share a zip; saved it instead");
  });

  it("saves a Markdown page the phone can't share, as it is", async () => {
    const share = phone((d) => d.files?.[0].type === "application/zip");
    vi.stubGlobal("fetch", async () => reply("p.md", "text/markdown"));
    const saved = vi.fn();
    await sharePageFile("/api/pages/a/download", "A page", saved);
    expect(share).not.toHaveBeenCalled();
    expect(saved.mock.calls[0][0].name).toBe("p.md");
  });
});

describe("sharePageHtml", () => {
  afterEach(() => vi.unstubAllGlobals());
  const article = {
    nodeType: 1,
    nodeName: "ARTICLE",
    childNodes: [{ nodeType: 3, nodeName: "#text", data: "hello", childNodes: [] }],
  } as unknown as HTMLElement;

  it("shares the page as an HTML file", async () => {
    const share = vi.fn(async () => {});
    vi.stubGlobal("navigator", { share, canShare: () => true });
    const saved = vi.fn();
    await sharePageHtml(article, "My page", saved);
    const file = (share.mock.calls[0] as unknown as [ShareData])[0].files?.[0] as File;
    expect(file.name).toBe("My-page.html");
    expect(await file.text()).toContain("hello");
    expect(saved).not.toHaveBeenCalled();
  });

  it("saves the file where this phone can't share one", async () => {
    const share = vi.fn(async () => {});
    vi.stubGlobal("navigator", { share, canShare: () => false });
    const saved = vi.fn();
    await sharePageHtml(article, "My page", saved);
    expect(share).not.toHaveBeenCalled();
    expect(saved.mock.calls[0][0].name).toBe("My-page.html");
  });
});
