import { describe, it, expect } from "vitest";
import { actionGate, applyTrip, defaultForm, fromLine, receiptSteps, stageNote, toPayload, withoutPayLine } from "./calcHelpers";
import type { PriceResult, Receipt } from "./types";
import { lead, setup } from "./testFixtures";

const ok = (patch: Partial<PriceResult> = {}): PriceResult => ({
  ok: true, message: "", warnings: [], availability: [], net: "70000.00", total: "70000.00", message_text: "Namaskara Kiran\nPay the advance here: rzp.io/…\nValid for 3 days.",
  approval: { needed: false, reasons: [], required_for_you: false }, ...patch,
});

describe("rate calculator helpers", () => {
  it("starts from the tenant's defaults and the first package", () => {
    const f = defaultForm(setup);
    expect(f).toMatchObject({ mode: "fixed", packageKey: "coorg-48", slab: "18", inclusive: true, ratePerDay: "25000", kmRate: "100",
      start: "2026-10-20", paymentLink: true });
    expect(f.addons.map(a => [a.name, a.price, a.unit, a.on])).toEqual([["Culinary kit", "5000", "one_time", false], ["Breakfast", "450", "per_guest_day", false]]);
  });

  it("fills the trip from the lead and ignores dates in the past", () => {
    const f = applyTrip(defaultForm(setup), { start_date: "2026-10-30", days: 2, guests: 6, package_key: "day-rate" }, setup);
    expect([f.start, f.days, f.guests, f.packageKey]).toEqual(["2026-10-30", 2, 6, "day-rate"]);
    expect(applyTrip(defaultForm(setup), { start_date: "2026-01-01" }, setup).start).toBe("2026-10-20");
    expect(applyTrip(defaultForm(setup), { route: "Hampi" }, setup).customTitle).toBe("Hampi");
  });

  it("builds the request: only ticked add-ons, the custom GST rate, the override in its basis", () => {
    const f = { ...defaultForm(setup), slab: "other", customRate: "12", overrideOn: true, overridePrice: "60,000", overrideReason: " repeat ",
      addons: defaultForm(setup).addons.map((a, i) => ({ ...a, on: i === 1 })) };
    expect(toPayload(f, "i1")).toMatchObject({
      mode: "fixed", package_key: "coorg-48", custom: null, gst_percent: "12", prices_include_gst: true, inquiry_id: "i1",
      addons: [{ name: "Breakfast", price: "450", unit: "per_guest_day" }], override: { price: "60000", reason: "repeat", show_usual: true },
    });
    expect(toPayload({ ...f, mode: "custom", ratePerDay: "" }, null)).toBeNull();
    expect(toPayload({ ...f, mode: "custom", plannedKm: "560" }, null)).toMatchObject({ package_key: null, custom: { rate_per_day: "25000", planned_km: "560", km_rate: "100" } });
  });

  it("gates the buttons: no lead = copy only, more than the limit off = Send for owner OK and no copy", () => {
    expect(actionGate({ result: ok(), lead: null, busy: false })).toMatchObject({ canCopy: true, canSend: false, canSave: false, sendLabel: "Send on WhatsApp" });
    expect(actionGate({ result: ok(), lead, busy: false })).toMatchObject({ canCopy: true, canSend: true, canSave: true, hint: null });
    const needs = actionGate({ result: ok({ approval: { needed: true, reasons: ["15% below"], required_for_you: true } }), lead, busy: false });
    expect(needs).toMatchObject({ needsOk: true, sendLabel: "Send for owner OK", canSend: true, canCopy: false });
    expect(actionGate({ result: ok(), lead, busy: true }).canSend).toBe(false);
    expect(actionGate({ result: { ok: false, message: "No price for Fri", warnings: [], availability: [] }, lead, busy: false }).hint).toBe("No price for Fri");
  });

  it("drops the placeholder link when copying without a lead", () => {
    expect(withoutPayLine(ok().message_text!)).toBe("Namaskara Kiran\nValid for 3 days.");
  });

  it("says where the sheet was opened from and what it filled in", () => {
    const ctx = { lead, add: null, trip: {}, guest_name: "Kiran Reddy", filled: ["route", "dates", "guests"] };
    expect(fromLine("inbox", ctx)).toBe("Opened from Kiran Reddy's WhatsApp chat. Route, dates and guests filled in from the chat.");
    expect(fromLine("call", { ...ctx, filled: ["dates"] })).toBe("Opened from the call with Kiran Reddy. Dates filled in from the call summary.");
    expect(fromLine("my_day", { lead: null, add: { phone: "+919845012345", known_name: null, known: false }, trip: {}, guest_name: null, filled: [] }))
      .toBe("Opened from My day (+919845012345). This number has no lead yet: add it below.");
    expect(fromLine("leads", { ...ctx, lead: { ...lead, kind: "new_trip", stage_label: "Sold" }, filled: [] }))
      .toContain("Their last trip was Sold, so this quote starts a new lead.");
    expect(fromLine(undefined, ctx)).toBe("");
  });

  it("explains the stage rule under the chosen lead", () => {
    expect(stageNote(lead)).toBe("General Enquiry now. Moves to Active when the quote is sent or copied.");
    expect(stageNote({ ...lead, stage_label: "Active" })).toBe("Active. Stage stays as it is.");
    expect(stageNote({ ...lead, kind: "new_trip", stage_label: "Sold" })).toContain("A new lead is made for this trip");
  });

  it("lists what got recorded", () => {
    const r: Receipt = {
      quote_id: "q1", quote_number: "Q-ABC", status: "issued", how: "copied", lead: { inquiry_id: "i1", guest_id: "g1", guest_name: "Kiran Reddy" },
      lead_created: false, stage: { from: "General Enquiry", to: "Active", moved: true }, follow_up_at: "2026-10-22T18:29:59+00:00",
      total: "70000.00", advance: "35000", valid_until: "2026-10-22", shared_via: "copied", approval: null, message: null,
      message_text: "...", payment_link: null,
    };
    const s = receiptSteps(r, { ...lead, created: true, matched_existing: true });
    expect(s.title).toBe("Copied and saved to the lead");
    expect(s.done).toEqual([
      "New lead added: Kiran Reddy, ••5678, from WhatsApp (joined to the person already in HAIP)",
      "Quote Q-ABC saved to Kiran's lead · copied", "Stage: General Enquiry → Active",
      "Follow-up in My day on Thu, 22 Oct, the day the quote expires",
      "Lead timeline and Leads360 card: latest quote ₹70,000 · copied · valid till Thu, 22 Oct",
    ]);
    expect(s.next[0]).toContain("₹35,000 advance is paid");
    const pending = receiptSteps({ ...r, how: "pending_approval", approval: { needed: true, reasons: ["15% below the suggested price"] } }, lead);
    expect(pending.title).toBe("Waiting for the owner's OK");
    const notSent = receiptSteps({ ...r, how: "saved", stage: { from: "RNR", to: "RNR", moved: false },
      message: { status: "not_sent", code: "template_not_approved", message: "Copy it instead." } }, lead);
    expect(notSent.warning).toBe("Copy it instead.") ;
    expect(notSent.done).toContain("Stage unchanged until the quote is sent or copied");
  });
});
