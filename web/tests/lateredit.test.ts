import { describe, expect, it } from "vitest";
import { mediaFields, mediaNow, mediaSays } from "../src/lateredit";

describe("a Later page's type", () => {
  it("reads the type it has, only if known", () => {
    expect(mediaNow({ media_type: "film" })).toBe("film");
    expect(mediaNow({ media_type: "vinyl" })).toBe("");
    expect(mediaNow(undefined)).toBe("");
  });
  it("says it with what it is for", () => {
    expect(mediaSays("book")).toBe("Book · To read");
    expect(mediaSays("game")).toBe("Game · To play");
    expect(mediaSays("")).toBe("none");
  });
  it("sends the type and its subtype, or takes the type off", () => {
    expect(mediaFields("podcast")).toEqual({ media_type: "podcast", subtype: "listen" });
    expect(mediaFields("")).toEqual({ media_type: null });
  });
});
