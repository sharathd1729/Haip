import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@/lib/api", () => ({ default: { post: vi.fn() } }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { QaScoreCard, type QaScore } from "./QaScoreCard";

const base: QaScore = {
  score_id: "s1", total_score: 4.45, max_score: 5, confidence: 0,
  agent_strengths: [], agent_growth_areas: [],
  criteria: [{ criterion: "greet", name: "Greeting", method: "YES_NO", score: 1, max_score: 1, evidence: "" }],
};

beforeEach(() => cleanup());

describe("QaScoreCard", () => {
  it("never prints a stray 0 for zero confidence or empty strengths", () => {
    const { container } = render(<QaScoreCard score={base} canCorrect onCorrected={() => {}} />);
    expect(screen.getByRole("button", { name: "Correct this score" })).toBeTruthy();
    expect(screen.queryByText(/Confidence/)).toBeNull();
    // only "4.45", "/5" and "1/1" carry digits; a leaked {0 && ...} would add a bare "0" text node
    const bareZero = [...container.querySelectorAll("*")].some(el =>
      [...el.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent?.trim() === "0"));
    expect(bareZero).toBe(false);
  });

  it("shows confidence, strengths and each criterion on its own scale", () => {
    render(<QaScoreCard score={{ ...base, confidence: 0.8, agent_strengths: ["Warm greeting"],
      criteria: [...base.criteria, { criterion: "needs", method: "ZERO_THREE", score: 2, max_score: 3, evidence: "" }] }}
      canCorrect={false} onCorrected={() => {}} />);
    expect(screen.getByText("Confidence: 80%")).toBeTruthy();
    expect(screen.getByText("Warm greeting")).toBeTruthy();
    expect(screen.getByText("1/1")).toBeTruthy();
    expect(screen.getByText("2/3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Correct this score" })).toBeNull();
  });
});
