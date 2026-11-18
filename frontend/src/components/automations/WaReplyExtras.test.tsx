import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { applyRepeat, WaReplyStatsLine } from "./WaReplyExtras";

describe("WhatsApp keyword reply options", () => {
  it("how often: one setting at a time", () => {
    const base = { message: "Hi", once_per_person: true };
    expect(applyRepeat(base, "12")).toEqual({ message: "Hi", repeat_after_hours: 12 });
    expect(applyRepeat({ message: "Hi", repeat_after_hours: 12 }, "once")).toEqual(base);
    expect(applyRepeat(base, "always")).toEqual({ message: "Hi" });
  });

  it("stats say the period and never divide by zero", () => {
    const text = (html: string) => html.replace(/<[^>]+>/g, "");
    expect(text(renderToStaticMarkup(<WaReplyStatsLine />))).toBe("Last 30 days: not sent yet");
    const s = { rule_id: "r", sent: 4, delivered: 3, read: 2, failed: 1, people: 3 };
    expect(text(renderToStaticMarkup(<WaReplyStatsLine stat={s} />))).toMatch(/Last 30 days: 4 sent · 75% delivered · 2 read · 3 people · 1 failed/);
    expect(text(renderToStaticMarkup(<WaReplyStatsLine stat={{ ...s, sent: 0, delivered: 0, read: 0 }} />))).toMatch(/none delivered/);
  });
});
