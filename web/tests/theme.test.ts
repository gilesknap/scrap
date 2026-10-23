import { describe, expect, test } from "vitest";
import { appPref, appTheme, drawingTheme, drawPref } from "../src/theme";

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
