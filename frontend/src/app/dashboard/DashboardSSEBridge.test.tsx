import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

const h = vi.hoisted(() => ({
  onEvent: (() => {}) as (p: Record<string, unknown>) => void,
  invalidate: vi.fn(),
  store: (s: Record<string, unknown>) => (pick: (x: Record<string, unknown>) => unknown) => pick(s),
}));
const { invalidate } = h;
const onEvent = (p: Record<string, unknown>) => h.onEvent(p);
vi.mock("next-auth/react", () => ({ useSession: () => ({ status: "authenticated" }) }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: h.invalidate }) }));
vi.mock("@/hooks/useInboxStream", () => ({ useInboxStream: (_on: boolean, cb: typeof h.onEvent) => { h.onEvent = cb; } }));
vi.mock("@/store/calls", () => ({ useCallsStore: h.store({ pushWrapUp: vi.fn() }) }));
vi.mock("@/store/inbox", () => ({ useInboxStore: h.store({ setAiDraft: vi.fn(), setPhoneDeclineAlert: vi.fn(), upsertConversation: vi.fn() }) }));
vi.mock("@/store/useNotificationsStore", () => ({ useNotificationsStore: h.store({ addEvent: vi.fn() }) }));

import { DashboardSSEBridge, QUEUE_REFRESH_MS } from "./DashboardSSEBridge";

const queueRefreshes = () => invalidate.mock.calls.filter(([a]) => a.queryKey[0] === "work-queue").length;

beforeEach(() => { vi.useFakeTimers(); invalidate.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("DashboardSSEBridge", () => {
  it("refreshes My day once for a burst of messages, not once per message", () => {
    render(<DashboardSSEBridge />);
    for (let i = 0; i < 5; i++) onEvent({ event: "message_received", conversation_id: `c${i}` });
    expect(queueRefreshes()).toBe(0);
    vi.advanceTimersByTime(QUEUE_REFRESH_MS);
    expect(queueRefreshes()).toBe(1);
    onEvent({ event: "message_received", conversation_id: "c9" });
    vi.advanceTimersByTime(QUEUE_REFRESH_MS);
    expect(queueRefreshes()).toBe(2);
  });

  it("still refreshes at once when the AI asks a manager", () => {
    render(<DashboardSSEBridge />);
    onEvent({ event: "consult_opened" });
    expect(queueRefreshes()).toBe(1);
  });
});
