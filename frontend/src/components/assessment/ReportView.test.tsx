import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FullReport, SummaryCard } from "./ReportView";
import type { AssessmentReport, AssessmentSummary } from "@/lib/assessment";
import fixture from "./__fixtures__/report.json";

// A real engine result (backend assessment_engine.project on the sample benchmarks), so this breaks if the shapes drift.
const report = fixture as unknown as AssessmentReport;

describe("FullReport", () => {
  it("shows the server's figures, the sketch and the PDF link", () => {
    const { container } = render(<FullReport report={report} id="lead-1" token="tok" />);
    expect(screen.getByRole("link", { name: /download pdf/i }).getAttribute("href")).toBe("/api/v1/public/assessment/lead-1/report.pdf?token=tok");
    expect(screen.getAllByText(/sample values/i).length).toBeGreaterThan(0);
    expect(container.querySelectorAll("svg[aria-label='Indicative zoning sketch of the plot'] rect")).toHaveLength(report.zoning.zones.length);
    expect(screen.getByText(report.cta.saas.title)).toBeTruthy();
    const likely = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(report.yearly.likely.revenue);
    expect(screen.getAllByText(likely).length).toBeGreaterThan(0);
  });
});

describe("SummaryCard", () => {
  it("shows the headline range only", () => {
    const summary: AssessmentSummary = {
      ...report, yearly_revenue: { low: report.yearly.low.revenue, likely: report.yearly.likely.revenue, high: report.yearly.high.revenue },
      investment_total: report.investment.total, payback_months_likely: report.payback_months.likely,
    };
    render(<SummaryCard summary={summary} />);
    expect(screen.getByText("Your estimate")).toBeTruthy();
    expect(screen.queryByText("Revenue by month")).toBeNull();
  });
});
