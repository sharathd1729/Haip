import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("@/components/calls/CallDetailPanel", () => ({ OUTCOMES: [] }));
vi.mock("@/components/quotes/SendQuoteButton", () => ({ SendQuoteButton: () => null }));

import { SummaryTiles } from "./CallListParts";

afterEach(cleanup);

describe("SummaryTiles", () => {
  it("shows skeletons, not numbers or 'all returned', until the summary arrives", () => {
    const { container } = render(<SummaryTiles rangeLabel="Today" onPick={() => {}} />);
    expect(screen.queryByText("all returned")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText("–")).toBeNull();
    expect(container.querySelectorAll("[data-slot='skeleton'], .animate-pulse").length).toBeGreaterThanOrEqual(5);
  });
});
