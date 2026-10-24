import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageBubble } from "./MessageBubble";

// The inbox hides the controls that send to a guest (approve a draft, retry, AI rewrite) from people without the
// conversations.send capability by not passing the handlers. The server refuses the calls regardless; these tests pin
// that the UI follows the same rule.

const base = { id: "m1", text: "Hello from the villa", direction: "outbound" as const, timestamp: "2026-10-12T10:00:00Z" };

describe("AI draft controls", () => {
  it("shows Approve, Tone and Translate when the user can send", () => {
    render(<MessageBubble {...base} isAiDraft onApprove={vi.fn()} onRewrite={vi.fn()} onEdit={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByRole("button", { name: /approve/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /tone/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /translate/i })).toBeTruthy();
  });

  it("wraps the action row so it never spills off the left edge on a phone", () => {
    render(<MessageBubble {...base} isAiDraft onApprove={vi.fn()} onRewrite={vi.fn()} onEdit={vi.fn()} onReject={vi.fn()} />);
    const row = screen.getByTestId("ai-draft-actions");
    expect(row.className).toContain("flex-wrap");
    expect(row.className).toContain("max-w-full");
    expect(row.contains(screen.getByRole("button", { name: /approve/i }))).toBe(true);
  });

  it("hides Approve, Tone and Translate when the user cannot send", () => {
    render(<MessageBubble {...base} isAiDraft onEdit={vi.fn()} onReject={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /tone/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /translate/i })).toBeNull();
  });
});

describe("Retry control", () => {
  it("shows Retry on a failed message when the user can send", () => {
    render(<MessageBubble {...base} status="failed" deliveryError="Provider rejected it" onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });

  it("hides Retry when the user cannot send", () => {
    render(<MessageBubble {...base} status="failed" deliveryError="Provider rejected it" />);
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });
});
