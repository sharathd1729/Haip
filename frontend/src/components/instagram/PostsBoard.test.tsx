import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

import { PostsBoard } from "./PostsBoard";
import type { IgRule } from "./automationTypes";

const posts = [
  { id: "m1", caption: "Comment PRICE for the villa", type: "reel", thumbnail: null, timestamp: "2026-11-20T14:00:00+0000" },
  { id: "m2", caption: "Sunset at the pool", type: "image", thumbnail: null, timestamp: "2026-11-18T14:00:00+0000" },
];
const rule = { id: "r1", name: "PRICE reel", trigger: "ig_comment_received", trigger_config: { media_id: "m1" }, action: "send_instagram_quick_reply",
  action_config: { message: "Hi" }, is_active: true, run_count: 3 } as unknown as IgRule;
const stat = (rules: string[], sent: number) => ({ rules, covered_by_any: false, people: sent, sent, public_replies: sent, opened: 0, clicks: 0 });

afterEach(cleanup);

describe("PostsBoard", () => {
  it("shows each post's automation and stats, and filters to posts without one", async () => {
    get.mockImplementation((url: string) => Promise.resolve({ data: url === "/instagram/media"
      ? { items: posts, next: null } : { posts: { m1: stat(["r1"], 4), m2: stat([], 0) } } }));
    const onSetUp = vi.fn();
    render(<QueryClientProvider client={new QueryClient()}><PostsBoard rules={[rule]} onSetUp={onSetUp} onEdit={vi.fn()} onCopy={vi.fn()} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByText("4 DMs · 0 opened · 0 clicks · 4 public replies")).toBeTruthy());
    expect(screen.getByText("Automation on")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Without" }));
    expect(screen.queryByText("Comment PRICE for the villa")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Set up" }));
    expect(onSetUp).toHaveBeenCalledWith(expect.objectContaining({ id: "m2" }));
  });
});
