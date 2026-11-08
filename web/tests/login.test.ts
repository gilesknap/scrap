// The login in front of scrap expired (an oauth2-proxy at DLS, Cloudflare Access): api() reads
// the proxy's redirect as LoginExpired, the views say so with Log in again, and that load is
// marked so the service worker leaves it (and the login's own pages) to the network.
import { afterEach, describe, expect, it, vi } from "vitest";
import { type FakeNode, fakeDocument } from "./fakedom";

vi.stubGlobal("document", fakeDocument());
const dispatch = vi.fn(() => true);
vi.stubGlobal("dispatchEvent", dispatch);
const fetch = vi.fn();
vi.stubGlobal("fetch", fetch);
const { ApiError, LoginExpired, api } = await import("../src/api");
const { marked, toNetwork, unmark } = await import("../src/login");
const { problem, relogin } = await import("../src/ui");
const { why } = await import("../src/why");

afterEach(() => fetch.mockReset());

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
/** What fetch gives for a redirect it was told not to follow: no status, no body, no headers. */
const opaque = () => ({ type: "opaqueredirect", ok: false, status: 0 }) as Response;

describe("api()", () => {
  it("does not follow redirects, and reads one as the login having expired", async () => {
    fetch.mockResolvedValue(opaque());
    const err = await api<never>("pages").catch((e: Error) => e);
    expect(err).toBeInstanceOf(LoginExpired);
    expect(err).not.toBeInstanceOf(ApiError);
    expect(err.message).toBe("your login has expired");
    expect(fetch).toHaveBeenCalledWith("/api/pages", { redirect: "manual" });
  });

  it("keeps the caller's options, and a change that met the redirect is not announced", async () => {
    fetch.mockResolvedValue(opaque());
    const init = { method: "PATCH", body: "{}" };
    await expect(api("pages/x", init)).rejects.toBeInstanceOf(LoginExpired);
    expect(fetch).toHaveBeenCalledWith("/api/pages/x", { redirect: "manual", ...init });
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("answers and errors as before", async () => {
    fetch.mockResolvedValue(json(200, { id: "x" }));
    await expect(api("pages/x")).resolves.toEqual({ id: "x" });
    fetch.mockResolvedValue(json(404, { detail: "Not found" }));
    const err = await api<never>("pages/y").catch((e: InstanceType<typeof ApiError>) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.message]).toEqual([404, "Not found"]);
  });

  it("lets a network failure through as it was (offline, not reached)", async () => {
    const offline = new TypeError("Failed to fetch");
    fetch.mockRejectedValue(offline);
    await expect(api("pages")).rejects.toBe(offline);
  });
});

describe("why()", () => {
  it("says the server's message, the login expired, or not reached", () => {
    expect(why(new ApiError(409, { detail: "Changed elsewhere" }))).toBe("Changed elsewhere");
    expect(why(new LoginExpired())).toBe("your login has expired");
    expect(why(new TypeError("Failed to fetch"))).toBe("can't reach the server");
    expect(why(new TypeError("Failed to fetch"), "offline?")).toBe("offline?");
    expect(why(new LoginExpired(), "offline?")).toBe("your login has expired");
  });
});

describe("problem()", () => {
  it("says the login expired, with Log in again", () => {
    const el = problem(new LoginExpired()) as unknown as FakeNode;
    expect(el.className).toBe("empty failed");
    expect(el.find("P")[0]?.textContent).toBe("Your login has expired.");
    const [button] = el.find("BUTTON");
    expect(button?.textContent).toBe("Log in again");
    expect(button?.className).toBe("primary");
    expect(button?.onclick).toBe(relogin);
  });

  it("still says the server can't be reached when it can't", () => {
    vi.stubGlobal("navigator", { onLine: true });
    const el = problem(new TypeError("Failed to fetch")) as unknown as FakeNode;
    expect(el.find("P")[0]?.textContent).toBe(
      "Can't reach the server. Check your connection or VPN.",
    );
    expect(el.find("BUTTON")[0]?.textContent).toBe("Retry");
    vi.unstubAllGlobals();
    vi.stubGlobal("document", fakeDocument());
    vi.stubGlobal("dispatchEvent", dispatch);
    vi.stubGlobal("fetch", fetch);
  });
});

describe("logging in again", () => {
  it("reloads this screen marked login=1, its own query kept", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { href: "https://scrap.example/search?q=tag%3Ax#top", assign });
    relogin();
    expect(assign).toHaveBeenCalledWith("https://scrap.example/search?q=tag%3Ax&login=1#top");
    expect(marked("https://scrap.example/p/a")).toBe("https://scrap.example/p/a?login=1");
  });

  it("takes the mark off once loaded, leaving the rest", () => {
    const q = new URLSearchParams("q=login&login=1&debug=1");
    expect(unmark(q)).toBe(true);
    expect(q.toString()).toBe("q=login&debug=1");
    expect(unmark(new URLSearchParams("q=x"))).toBe(false);
  });

  it("sends the login's pages and a marked load to the network, and nothing else", () => {
    const net = (path: string) => toNetwork(new URL(path, "https://scrap.example"));
    expect(net("/oauth2/start?rd=%2F")).toBe(true);
    expect(net("/oauth2/callback?code=c&state=s")).toBe(true);
    expect(net("/cdn-cgi/access/authorized?token=t")).toBe(true);
    expect(net("/p/a?login=1")).toBe(true);
    expect(net("/")).toBe(false);
    expect(net("/p/a")).toBe(false);
    expect(net("/search?q=login")).toBe(false);
    expect(net("/oauth2x")).toBe(false);
    expect(net("/p/oauth2/x")).toBe(false);
  });
});
