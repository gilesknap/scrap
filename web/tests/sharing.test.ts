import { afterEach, describe, expect, it, vi } from "vitest";
import { tapExpired } from "../src/sharing";

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
