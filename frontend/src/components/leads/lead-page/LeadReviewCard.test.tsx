import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const put = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({ default: { put: (...a: unknown[]) => put(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { LeadReviewCard } from "./LeadReviewCard";
import { LogCallSheet } from "./LogCallSheet";

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => { put.mockReset(); post.mockReset(); put.mockResolvedValue({ data: {} }); post.mockResolvedValue({ data: { callbacks_closed: 1 } }); });
afterEach(cleanup);

describe("LeadReviewCard", () => {
  it("records Valid with the three checks and the note", async () => {
    wrap(<LeadReviewCard inquiryId="i1" leadType="guest" validation={null} canEdit />);
    expect(screen.getByText("Not reviewed yet.")).toBeTruthy();
    await userEvent.click(screen.getByLabelText("Dates confirmed"));
    await userEvent.click(screen.getByLabelText("Clear intent to book"));
    await userEvent.type(screen.getByPlaceholderText("Note (optional)"), "2 nights");
    await userEvent.click(screen.getByRole("button", { name: /^Valid$/ }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/leads/i1/validation",
      { valid: true, dates_confirmed: true, budget_fits: false, clear_intent: true, note: "2 nights" }));
  });

  it("changes the lead type and says who reviewed it", async () => {
    wrap(<LeadReviewCard inquiryId="i1" leadType="b2b" canEdit
      validation={{ status: "invalid", by_name: "Asha", at: "2026-10-22T05:00:00Z" }} />);
    expect(screen.getByText(/Not counted in the guest lead numbers/)).toBeTruthy();
    expect(screen.getByText(/Marked Not valid by Asha/)).toBeTruthy();
    await userEvent.click(screen.getByRole("radio", { name: "Guest" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/leads/i1/lead-type", { lead_type: "guest" }));
  });

  it("shows the automatic check with its reasons and follow-up notes", () => {
    wrap(<LeadReviewCard inquiryId="i1" leadType="guest" validation={null} canEdit
      validity={{ enabled: true, auto_valid: false, reasons: ["Location: Hyderabad (not Bengaluru)"], notes: ["No check-in date yet"],
        location: "Hyderabad", status: "invalid", source: "rule" }} />);
    expect(screen.getByText("Automatic check: Not valid")).toBeTruthy();
    expect(screen.getByText("Location: Hyderabad (not Bengaluru)")).toBeTruthy();
    expect(screen.getByText("To follow up: No check-in date yet")).toBeTruthy();
  });

  it("is read-only without edit rights", () => {
    wrap(<LeadReviewCard inquiryId="i1" leadType="guest" validation={null} canEdit={false} />);
    expect(screen.queryByRole("button", { name: /^Valid$/ })).toBeNull();
  });
});

describe("LogCallSheet", () => {
  it("logs a connected call with its minutes and note", async () => {
    wrap(<LogCallSheet open onClose={vi.fn()} inquiryId="i9" name="Ravi" />);
    await userEvent.type(screen.getByPlaceholderText("e.g. 5"), "4");
    await userEvent.type(screen.getByPlaceholderText("What did you agree?"), "Wants Coorg");
    await userEvent.click(screen.getByRole("button", { name: /Log the call/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i9/log-call", { outcome: "connected", note: "Wants Coorg", duration_minutes: 4 }));
  });

  it("logs an unanswered attempt without minutes", async () => {
    wrap(<LogCallSheet open onClose={vi.fn()} inquiryId="i9" name="Ravi" />);
    await userEvent.click(screen.getByRole("radio", { name: /No answer/ }));
    expect(screen.queryByPlaceholderText("e.g. 5")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Log the call/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/leads/i9/log-call", { outcome: "no_answer", note: undefined, duration_minutes: undefined }));
  });
});
