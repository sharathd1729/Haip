import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a), patch: (...a: unknown[]) => patch(...a),
  },
}));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { KnowledgeFreshnessPanel, type FreshnessReport } from "./KnowledgeFreshnessPanel";
import { SocialApprovalQueue } from "./SocialApprovalQueue";
import { SourceBadge } from "./SourceBadge";

const report: FreshnessReport = {
  generated_at: "2026-10-18T10:00:00Z",
  settings: { auto_approve_social: false, social_sync: true, website_recrawl: false, social_max_age_days: 180 },
  price_mode: "handoff",
  sources: [{ source: "instagram", label: "Instagram posts", total: 3, used_by_bot: 1, waiting_approval: 2, indexing: 0, failed: 0,
              gave_up: 0, out_of_date: 0, flagged_price: 1, last_updated: "2026-10-17T10:00:00Z", last_indexed: null }],
  business_data: { published: 4, drafts: 2, scheduled: 0, last_published_at: null },
  records: { properties: 2, properties_last_updated: null, rate_tables_last_updated: null },
  instagram: { connected: true, sync_enabled: true, last_run_at: null, last_ok_at: null, last_error: null },
  website: { pages: 1, recrawl_enabled: false, last_read_at: null },
  warnings: [{ code: "unpublished_drafts", level: "warning", text: "2 business-data draft(s) are not published. The bot reads only published versions." }],
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => { get.mockReset(); post.mockReset(); put.mockReset(); patch.mockReset(); });
afterEach(() => cleanup());

describe("What the bot knows", () => {
  it("shows per-source counts and warnings, and Re-index now calls the refresh endpoint", async () => {
    get.mockResolvedValue({ data: report });
    post.mockResolvedValue({ data: { queued_for_indexing: 2, instagram_sync_queued: true } });
    wrap(<KnowledgeFreshnessPanel />);
    expect(await screen.findByText("1 used")).toBeTruthy();
    expect(screen.getByText("2 waiting approval")).toBeTruthy();
    expect(screen.getByText(report.warnings[0].text)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Re-index now/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/knowledge/refresh"));
  });

  it("saves a setting through the source-settings endpoint", async () => {
    get.mockResolvedValue({ data: report });
    put.mockResolvedValue({ data: { ...report.settings, auto_approve_social: true } });
    wrap(<KnowledgeFreshnessPanel />);
    await userEvent.click(await screen.findByLabelText(/Use new posts without asking me/));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/knowledge/source-settings", { auto_approve_social: true }));
  });

  it("is hidden for a role that may not see it", async () => {
    get.mockRejectedValue({ response: { status: 403 } });
    wrap(<KnowledgeFreshnessPanel />);
    await waitFor(() => expect(screen.queryByText("What the bot knows")).toBeNull());
  });
});

describe("Approval queue", () => {
  it("lists only social and imported items and approves with one click", async () => {
    get.mockResolvedValue({ data: { items: [
      { id: "k1", source: "instagram", content: "Mysore Dasara route open", content_flags: ["mentions_price"], created_at: "2026-10-17T10:00:00Z",
        source_published_at: "2026-10-16T10:00:00Z", source_url: "https://www.instagram.com/p/x/" },
      { id: "k2", source: "website", content: "Website text", created_at: "2026-10-17T10:00:00Z" },
    ], total: 2 } });
    patch.mockResolvedValue({ data: {} });
    wrap(<SocialApprovalQueue />);
    expect(await screen.findByText("Mysore Dasara route open")).toBeTruthy();
    expect(screen.queryByText("Website text")).toBeNull();
    expect(screen.getByText(/Quotes a price/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/knowledge/k1", { review_status: "approved" }));
  });

  it("renders nothing when no item is waiting", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0 } });
    wrap(<SocialApprovalQueue />);
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Waiting for your approval")).toBeNull());
  });

  it("names each source in plain words", () => {
    wrap(<><SourceBadge source="manual" /><SourceBadge source="meta_ad" /><SourceBadge source="instagram" /></>);
    expect(screen.getByText("Owner")).toBeTruthy();
    expect(screen.getByText("Ad")).toBeTruthy();
    expect(screen.getByText("Instagram")).toBeTruthy();
  });
});
