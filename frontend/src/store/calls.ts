/**
 * Calls store — tracks call list filters and the recently-completed wrap-up queue.
 */
import { create } from "zustand";

export type CallDisposition =
  | "pending"
  | "qualified"
  | "booked"
  | "lost"
  | "spam"
  | "callback";

export interface CallSummary {
  id: string;
  started_at: string;
  duration_seconds: number;
  direction: "inbound" | "outbound";
  guest_phone: string;
  guest_name?: string;
  agent_name?: string;
  disposition: CallDisposition;
  qa_score?: number; // 0–100
  has_transcript: boolean;
  has_wrap_up: boolean;
}

export interface CallFilters {
  dateFrom?: string;
  dateTo?: string;
  disposition?: CallDisposition | "";
  scoreMin?: number;
  scoreMax?: number;
  agentId?: string;
  search?: string;
}

interface CallsState {
  filters: CallFilters;
  wrapUpQueue: string[]; // call IDs with freshly-completed wrap-ups (shown as badges)

  setFilters: (f: Partial<CallFilters>) => void;
  resetFilters: () => void;
  pushWrapUp: (callId: string) => void;
  dismissWrapUp: (callId: string) => void;
}

const DEFAULT_FILTERS: CallFilters = {};

export const useCallsStore = create<CallsState>((set, get) => ({
  filters: DEFAULT_FILTERS,
  wrapUpQueue: [],

  setFilters: (f) => set({ filters: { ...get().filters, ...f } }),
  resetFilters: () => set({ filters: DEFAULT_FILTERS }),

  pushWrapUp: (callId) =>
    set({ wrapUpQueue: [...new Set([...get().wrapUpQueue, callId])] }),

  dismissWrapUp: (callId) =>
    set({ wrapUpQueue: get().wrapUpQueue.filter(id => id !== callId) }),
}));
