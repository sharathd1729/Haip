import { describe, expect, it } from "vitest";
import { addHoliday, buttonProblem, changedSections, copyToAll, dayHint, DAYS, fillPreview, locationPreview, type Day, type DayKey, type Sections } from "./waBot";

const day = (open = "09:00", close = "21:00", closed = false): Day => ({ open, close, closed });
const weekly = Object.fromEntries(DAYS.map(d => [d, day()])) as Record<DayKey, Day>;

describe("waBot helpers", () => {
  it("fills the first name in the preview", () => {
    expect(fillPreview("Hi {first_name}, welcome! {first_name}")).toBe("Hi Ananya, welcome! Ananya");
  });

  it("puts the map link on its own line", () => {
    expect(locationPreview({ enabled: true, text: "Thanks {first_name}!", map_link: " https://maps.app/x " })).toBe("Thanks Ananya!\nhttps://maps.app/x");
    expect(locationPreview({ enabled: true, text: "Thanks!", map_link: "" })).toBe("Thanks!");
  });

  it("keeps one holiday per date, sorted, and ignores a blank date", () => {
    let list = addHoliday([], "2026-12-25", "Christmas");
    list = addHoliday(list, "2026-11-08", "Diwali");
    list = addHoliday(list, "2026-12-25", "Xmas");
    expect(list).toEqual([{ date: "2026-11-08", label: "Diwali" }, { date: "2026-12-25", label: "Xmas" }]);
    expect(addHoliday(list, "", "x")).toBe(list);
  });

  it("copies one day to the whole week as separate objects", () => {
    const w = copyToAll({ ...weekly, mon: day("10:00", "19:00") }, "mon");
    expect(DAYS.every(d => w[d].open === "10:00")).toBe(true);
    w.tue.open = "11:00";
    expect(w.wed.open).toBe("10:00");
  });

  it("checks reply buttons against Meta's limits", () => {
    expect(buttonProblem(["Check dates", ""])).toBeNull();
    expect(buttonProblem(["A label that is far too long"])).toMatch(/20/);
    expect(buttonProblem(["Yes", "yes"])).toMatch(/different/);
    expect(buttonProblem(["a", "b", "c", "d"])).toMatch(/3/);
  });

  it("explains closed, all-day and overnight days", () => {
    expect(dayHint(day("09:00", "21:00", true))).toBe("Closed all day");
    expect(dayHint(day("09:00", "09:00"))).toBe("Open all day");
    expect(dayHint(day("18:00", "02:00"))).toBe("Closes after midnight");
    expect(dayHint(day())).toBe("");
  });

  it("sends only the sections that changed", () => {
    const s: Sections = {
      hours: { weekly, holidays: [] },
      welcome: { enabled: false, text: "Hi", buttons: [], also_when_ai_replies: true },
      location_reply: { enabled: false, text: "Thanks", map_link: "" },
      opt_confirm: { custom: true, stop_text: "Bye", start_text: "Hello" },
    };
    expect(changedSections(s, { ...s, welcome: { ...s.welcome, enabled: true } })).toEqual({ welcome: { ...s.welcome, enabled: true } });
    expect(changedSections(s, s)).toEqual({});
  });
});
