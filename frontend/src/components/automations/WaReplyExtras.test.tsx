import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { applyRepeat, moveFile, readFiles, withFiles, WaReplyStatsLine } from "./WaReplyExtras";

describe("WhatsApp keyword reply options", () => {
  it("files: an old single-file rule reads as a one-item list and saves as files", () => {
    const pdf = { key: "t/wa_replies/a.pdf", kind: "document" as const, filename: "Menu.pdf" };
    expect(readFiles({ message: "Hi", file: pdf })).toEqual([pdf]);
    expect(readFiles({ message: "Hi", file: { key: "" } })).toEqual([]);
    expect(readFiles({ files: [pdf], file: { key: "old" } })).toEqual([pdf]);
    expect(withFiles({ message: "Hi", file: pdf }, [pdf, pdf])).toEqual({ message: "Hi", files: [pdf, pdf] });
  });

  it("files: move up and down, unchanged at the ends", () => {
    const f = (k: string) => ({ key: k, kind: "document" as const });
    const list = [f("a"), f("b"), f("c")];
    expect(moveFile(list, 1, -1).map(x => x.key)).toEqual(["b", "a", "c"]);
    expect(moveFile(list, 1, 1).map(x => x.key)).toEqual(["a", "c", "b"]);
    expect(moveFile(list, 0, -1)).toBe(list);
    expect(moveFile(list, 2, 1)).toBe(list);
  });

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
