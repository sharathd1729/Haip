import { describe, expect, it } from "vitest";
import { studioError } from "./types";
import { emptyPayload } from "./PayloadForm";
import { sentence } from "./BrainPanels";

const err = (detail: unknown) => ({ response: { data: { detail } } });

describe("studioError", () => {
  it("joins the message and the problems the API returns", () => {
    expect(studioError(err({ code: "content_not_allowed", message: "Breaks a rule.", problems: ["Mentions a price."] }), "x"))
      .toBe("Breaks a rule. Mentions a price.");
  });
  it("turns the generic permission error into plain words", () => {
    expect(studioError(err("Insufficient permissions"), "x")).toBe("Your role can't do that.");
  });
  it("falls back when there is no detail", () => {
    expect(studioError(new Error("network"), "Try again.")).toBe("Try again.");
  });
});

describe("emptyPayload", () => {
  it("starts a carousel with the two slides Instagram requires", () => {
    expect((emptyPayload("carousel").slides as unknown[]).length).toBe(2);
  });
  it("gives a story a frame and no caption", () => {
    const p = emptyPayload("story");
    expect(p.frames).toHaveLength(1);
    expect(p.caption).toBeUndefined();
  });
});

describe("sentence", () => {
  it("adds a full stop only when the text has none", () => {
    expect(sentence("Scenic escapes.")).toBe("Scenic escapes.");
    expect(sentence("Scenic escapes ")).toBe("Scenic escapes.");
    expect(sentence("Really?")).toBe("Really?");
  });
});
