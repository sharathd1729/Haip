import { describe, it, expect } from "vitest";
import { groupLeads, leadGroup } from "./leadGroups";
import type { LeadCard } from "./LeadCard";

// 17 Oct 2026, 10:00 IST
const NOW = new Date("2026-10-17T04:30:00Z");
const lead = (id: string, patch: Partial<LeadCard> = {}): LeadCard => ({
  inquiry_id: id, guest_id: id, display_name: id, profile_completeness_pct: 50, identity_signals: [],
  inquiry_stage: "active", stage_key: "active", created_at: "2026-10-01T05:00:00Z", ...patch,
});

describe("leadGroup", () => {
  it("puts anything waiting on a person in Act now", () => {
    expect(leadGroup(lead("a", { sla_breached: true }), NOW)).toBe("now");
    expect(leadGroup(lead("b", { response_time_status: "waiting" }), NOW)).toBe("now");
    expect(leadGroup(lead("c", { pending_draft: { message_id: "m", conversation_id: "c", preview: "hi" } }), NOW)).toBe("now");
    expect(leadGroup(lead("d", { needs_agent_followup: true }), NOW)).toBe("now");
  });
  it("uses the India date for Today: 00:30 IST counts, 23:30 IST the day before does not", () => {
    expect(leadGroup(lead("e", { last_touch_at: "2026-10-16T19:00:00Z" }), NOW)).toBe("today");   // 17 Oct 00:30 IST
    expect(leadGroup(lead("f", { last_touch_at: "2026-10-16T18:00:00Z" }), NOW)).toBe("later");   // 16 Oct 23:30 IST
  });
  it("leaves answered, untouched leads for Later", () => {
    expect(leadGroup(lead("g", { response_time_status: "responded" }), NOW)).toBe("later");
  });
});

describe("groupLeads", () => {
  it("returns non-empty groups in Act now, Today, Later order, keeping server order inside each", () => {
    const g = groupLeads([lead("x"), lead("y", { sla_breached: true }), lead("z", { created_at: "2026-10-17T03:00:00Z" }), lead("w", { sla_breached: true })], NOW);
    expect(g.map(x => [x.key, x.leads.map(l => l.inquiry_id)])).toEqual([["now", ["y", "w"]], ["today", ["z"]], ["later", ["x"]]]);
  });
});
