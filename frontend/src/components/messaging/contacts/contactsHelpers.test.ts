import { describe, expect, it } from "vitest";
import { bulkTarget, confirmLabel, enrolToast, netGrowth, plural, resultToast } from "./contactsHelpers";

describe("contacts helpers", () => {
  it("targets the ticked rows or everyone matching", () => {
    expect(bulkTarget(["a", "b"], false, { tag: "vip" })).toEqual({ ids: ["a", "b"] });
    expect(bulkTarget(["a"], true, { tag: "vip" })).toEqual({ filter: { tag: "vip" } });
  });

  it("pluralises with Indian digit grouping", () => {
    expect(plural(1)).toBe("1 contact");
    expect(plural(125000)).toBe("1,25,000 contacts");
  });

  it("confirms with the count", () => {
    expect(confirmLabel("opt_out", 12)).toBe("Opt out 12 contacts? They will stop getting campaigns.");
    expect(confirmLabel("add_to_list", 1, "Weddings")).toBe('Add 1 contact to "Weddings"?');
  });

  it("toasts what changed and notes the rest", () => {
    expect(resultToast("add_tag", 23, 23, "vip")).toBe('Tagged 23 contacts "vip"');
    expect(resultToast("opt_out", 2, 5)).toBe("Opted out 2 contacts (3 contacts already opted out)");
  });

  it("explains skipped contacts after a drip", () => {
    const r = { selected: 5, enrolled: 3, started: 3, queued: false, batches: 0, skipped: { opted_out: 1, not_a_guest: 1 } };
    expect(enrolToast(r, "Wedding drip")).toBe(
      'Started "Wedding drip" for 3 contacts. Skipped: 1 contact opted out, 1 contact not in your guest list yet.');
    expect(enrolToast({ ...r, queued: true, enrolled: 120, batches: 3, skipped: { opted_out: 0, not_a_guest: 0 } }, "D"))
      .toBe('"D" will start for 120 contacts over the next 3 minutes.');
  });

  it("nets growth", () => {
    expect(netGrowth([{ date: "x", new: 4, opted_out: 1 }, { date: "y", new: 0, opted_out: 2 }])).toBe(1);
  });
});
