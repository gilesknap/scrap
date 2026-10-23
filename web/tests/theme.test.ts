import { describe, expect, test, vi } from "vitest";
import {
  appPref,
  appTheme,
  drawingTheme,
  drawPref,
  getAppPref,
  getDrawPref,
  setAppPref,
  setDrawPref,
} from "../src/theme";

describe("app theme", () => {
  test("system follows the OS, a choice overrides it", () => {
    expect(appTheme("system", true)).toBe("dark");
    expect(appTheme("system", false)).toBe("light");
    expect(appTheme("light", true)).toBe("light");
    expect(appTheme("dark", false)).toBe("dark");
  });
  test("anything stored but light or dark is system", () => {
    expect(appPref("dark")).toBe("dark");
    expect(appPref("light")).toBe("light");
    expect(appPref(null)).toBe("system");
    expect(appPref("sepia")).toBe("system");
  });
});

describe("drawings theme", () => {
  test("light by default, whatever the app is", () => {
    expect(drawPref(null)).toBe("light");
    expect(drawPref("junk")).toBe("light");
    expect(drawingTheme(drawPref(null), "dark")).toBe("light");
  });
  test("a choice stands, same-as-app follows the app", () => {
    expect(drawingTheme(drawPref("dark"), "light")).toBe("dark");
    expect(drawingTheme(drawPref("app"), "dark")).toBe("dark");
    expect(drawingTheme(drawPref("app"), "light")).toBe("light");
  });
});

describe("with storage refused", () => {
  test("a choice still holds for the session", () => {
    const refuse = () => {
      throw new Error("denied");
    };
    vi.stubGlobal("localStorage", { getItem: refuse, setItem: refuse, removeItem: refuse });
    vi.stubGlobal("document", {
      documentElement: { dataset: {}, removeAttribute() {} },
      querySelectorAll: () => [],
    });
    setAppPref("dark");
    setDrawPref("app");
    expect(getAppPref()).toBe("dark");
    expect(getDrawPref()).toBe("app");
    vi.unstubAllGlobals();
  });
});
