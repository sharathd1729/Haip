import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ReadinessList, type ReadinessChecklist } from "./SalesAgentSettingsCard";

const checklist: ReadinessChecklist = {
  mode: "suggest", suggest_ready: false, autopilot_ready: false,
  rows: [
    { key: "agent_on", group: "suggest", ok: true, label: "Sales agent switched on", detail: "Now: suggest.", fix: null },
    { key: "razorpay", group: "suggest", ok: false, label: "Razorpay connected", detail: "No payment link can be made.",
      fix: { href: "/dashboard/settings/payments", label: "Connect Razorpay" } },
    { key: "link_policy", group: "autopilot", ok: false, label: "AI may send payment links",
      detail: "Payment links always wait for a person's tap while the learning loop is set up.", fix: null },
    { key: "webhook", group: "after", ok: true, label: "Razorpay can reach HAIP", detail: "Payments arrive within seconds.", fix: null },
  ],
};

afterEach(() => cleanup());

describe("Sales agent readiness", () => {
  it("groups the steps, says what is missing and links to where it is fixed", () => {
    render(<ReadinessList checklist={checklist} />);
    expect(screen.getByText("To prepare quotes a person sends (Suggest)")).toBeTruthy();
    expect(screen.getByText("After the guest pays")).toBeTruthy();
    const fix = screen.getByRole("link", { name: "Connect Razorpay" });
    expect(fix.getAttribute("href")).toBe("/dashboard/settings/payments");
    expect(screen.getByText(/while the learning loop is set up/)).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(1);             // a row with no fix (the learning cap) offers no link
    expect(screen.getAllByText("Not ready")).toHaveLength(2);
  });
});
