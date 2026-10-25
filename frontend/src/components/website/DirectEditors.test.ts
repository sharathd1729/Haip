import { describe, expect, it } from "vitest";
import { contrastWords, plainProblems } from "./DirectEditors";

describe("contrastWords", () => {
  it("turns the server's contrast problems into plain words", () => {
    const out = contrastWords(["tokens.palette: palette fails WCAG AA contrast: ink on surface: 1.62:1, needs 4.5:1; "
      + "button text on primary: 2.10:1, needs 4.5:1"]);
    expect(out).toBe("Text on the background is hard to read (1.6 to 1, needs 4.5). Writing on the buttons is hard to read "
      + "(2.1 to 1, needs 4.5). Make one of those colours darker or lighter.");
  });

  it("says nothing for a problem that isn't about colours", () => {
    expect(contrastWords(["pages.0.sections.1.slots: a price was typed into the text text"])).toBe("");
  });
});

describe("plainProblems", () => {
  it("drops the technical place and words a typed price for an owner", () => {
    const e = { response: { data: { detail: { message: "x", problems: [
      "pages.0.sections.0.slots: a price was typed into the hero text ('₹4,500'): prices come only from live HAIP data"] } } } };
    expect(plainProblems(e)).toBe("Please take out \"₹4,500\": prices can't be typed. HAIP shows your live prices by itself.");
  });
});
