"use client";
// Data for the personal call screens (/api/v1/me/*). One query key family so a reminder ticked anywhere updates the
// call page, the reminders list and the reminder counts on the calls list together.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ActionItem, CallDetail, CallsPage, Reminder } from "@/lib/personal";

const WORKING = new Set(["transcribing", "analysing"]);

export function useCallsPages() {
  return useInfiniteQuery<CallsPage>({
    queryKey: ["me", "calls"],
    queryFn: ({ pageParam }) => api.get("/me/calls", { params: pageParam ? { before: pageParam } : {} }).then(r => r.data),
    initialPageParam: null as string | null,
    getNextPageParam: last => (last.has_more ? last.calls[last.calls.length - 1]?.at ?? undefined : undefined),
    // A call still being transcribed or summarised becomes ready on its own: look again while any is working.
    refetchInterval: q => (q.state.data?.pages[0]?.calls.some(c => WORKING.has(c.status)) ? 20_000 : false),
  });
}

export function useCallDetail(id: string | null) {
  return useQuery<CallDetail>({
    queryKey: ["me", "call", id],
    queryFn: () => api.get(`/me/calls/${id}`).then(r => r.data),
    enabled: !!id,
    refetchInterval: q => (q.state.data && WORKING.has(q.state.data.status) ? 15_000 : false),
  });
}

export function useReminders(status: "open" | "done") {
  return useQuery<{ reminders: Reminder[] }>({
    queryKey: ["me", "reminders", status],
    queryFn: () => api.get("/me/reminders", { params: { status } }).then(r => r.data),
  });
}

/** Tick a reminder done (or open again). Shows the change at once; puts it back if the server says no. */
export function useToggleReminder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ callId, id, done }: { callId: string; id: string; done: boolean }) =>
      api.patch<ActionItem>(`/me/calls/${callId}/reminders/${id}`, { done }).then(r => r.data),
    onMutate: async ({ callId, id, done }) => {
      const key = ["me", "call", callId];
      await qc.cancelQueries({ queryKey: key });
      const before = qc.getQueryData<CallDetail>(key);
      if (before?.memory) {
        qc.setQueryData<CallDetail>(key, {
          ...before,
          memory: { ...before.memory, action_items: before.memory.action_items.map(a => (a.id === id ? { ...a, done } : a)) },
        });
      }
      return { key, before };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.before) qc.setQueryData(ctx.key, ctx.before);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
