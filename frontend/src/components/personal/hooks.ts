"use client";
// Data for the personal call screens (/api/v1/me/*). One query key family so a reminder ticked anywhere updates the
// call page, the reminders list and the reminder counts on the calls list together.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ActionItem, AskChat, CalEvent, CallDetail, CallsPage, Folder, Memory, MemoryChange, MemoryPatch, Reminder } from "@/lib/personal";

const WORKING = new Set(["transcribing", "analysing"]);

export function useCallsPages(filter: { q?: string; category?: string; folder?: string } = {}) {
  const params = {
    ...(filter.q?.trim() ? { q: filter.q.trim() } : {}),
    ...(filter.category ? { category: filter.category } : {}),
    ...(filter.folder ? { folder: filter.folder } : {}),
  };
  return useInfiniteQuery<CallsPage>({
    queryKey: ["me", "calls", params],
    queryFn: ({ pageParam }) => api.get("/me/calls", { params: { ...params, ...(pageParam ? { before: pageParam } : {}) } }).then(r => r.data),
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

/** Correct the memory: shown at once, put back if the server says no. Every list that shows the call refreshes after. */
export function useEditMemory(callId: string) {
  const qc = useQueryClient();
  const key = ["me", "call", callId];
  return useMutation({
    mutationFn: (patch: MemoryPatch) =>
      api.patch<{ memory: Memory; changed: string[] }>(`/me/calls/${callId}/memory`, patch).then(r => r.data),
    onMutate: async patch => {
      await qc.cancelQueries({ queryKey: key });
      const before = qc.getQueryData<CallDetail>(key);
      if (before?.memory) qc.setQueryData<CallDetail>(key, { ...before, memory: { ...before.memory, ...patch } as Memory });
      return { before };
    },
    onError: (_e, _v, ctx) => { if (ctx?.before) qc.setQueryData(key, ctx.before); },
    onSuccess: data => {
      const now = qc.getQueryData<CallDetail>(key);
      if (now) qc.setQueryData<CallDetail>(key, { ...now, memory: data.memory, title: data.memory.title });
    },
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me"] }); },
  });
}

export function useMemoryHistory(callId: string, enabled: boolean) {
  return useQuery<{ changes: MemoryChange[]; summarised_at: string | null }>({
    queryKey: ["me", "call", callId, "history"],
    queryFn: () => api.get(`/me/calls/${callId}/history`).then(r => r.data),
    enabled,
  });
}

export function useUndoChange(callId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) => api.post(`/me/calls/${callId}/history/${entryId}/undo`).then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me"] }); },
  });
}

// ─── Folders (/me/folders) ───────────────────────────────────────────────────

export function useFolders() {
  return useQuery<{ folders: Folder[]; unclassified: number }>({
    queryKey: ["me", "folders"],
    queryFn: () => api.get("/me/folders").then(r => r.data),
  });
}

/** Make (no id) or change a folder. Recent calls are sorted into it in the background, so lists refresh a moment later. */
export function useSaveFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<Folder>) =>
      (id ? api.patch<Folder>(`/me/folders/${id}`, body) : api.post<Folder>("/me/folders", body)).then(r => r.data),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["me"] }), 6000);
    },
  });
}

export function useDeleteFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/me/folders/${id}`).then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me"] }); },
  });
}

/** Put a call in a folder, or take it out (it then stays out of automatic sorting). */
export function useFolderCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ folderId, callId, add }: { folderId: string; callId: string; add: boolean }) =>
      (add ? api.post(`/me/folders/${folderId}/calls`, { call_id: callId }) : api.delete(`/me/folders/${folderId}/calls/${callId}`)).then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me"] }); },
  });
}

// ─── Calendar (/me/calendar) ─────────────────────────────────────────────────

export function useCalendar(month: string) {
  return useQuery<{ events: CalEvent[]; today: string }>({
    queryKey: ["me", "calendar", month],
    queryFn: () => api.get("/me/calendar", { params: { month } }).then(r => r.data),
  });
}

/** Make (no id) or change an event. */
export function useSaveEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<CalEvent>) =>
      (id ? api.patch<CalEvent>(`/me/calendar/${id}`, body) : api.post<CalEvent>("/me/calendar", body)).then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me", "calendar"] }); },
  });
}

export function useDeleteEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/me/calendar/${id}`).then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me", "calendar"] }); },
  });
}

export function useGoogleCalendar() {
  return useQuery<{ available: boolean; connected: boolean }>({
    queryKey: ["me", "calendar-google"],
    queryFn: () => api.get("/me/calendar/google").then(r => r.data),
  });
}

export function useDisconnectGoogle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete("/me/calendar/google").then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me"] }); },
  });
}

// ─── Ask Yaad chats (/me/asks) ─────────────────────────────────────────────

export function useAskChats(folderId?: string) {
  return useQuery<AskChat[]>({
    queryKey: ["me", "asks", folderId ?? "all"],
    queryFn: () => api.get("/me/asks", { params: folderId ? { folder_id: folderId } : {} }).then(r => r.data.chats),
  });
}

export function useAskChat(id: string | null) {
  return useQuery<AskChat>({
    queryKey: ["me", "ask-chat", id],
    queryFn: () => api.get(`/me/asks/${id}`).then(r => r.data),
    enabled: !!id,
  });
}

export function useAskSuggestions(folderId?: string) {
  return useQuery<string[]>({
    queryKey: ["me", "ask-suggestions", folderId ?? "all"],
    queryFn: () => api.get("/me/asks/suggestions", { params: folderId ? { folder_id: folderId } : {} }).then(r => r.data.suggestions),
    staleTime: 5 * 60_000,
  });
}

export function useDeleteChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/me/asks/${id}`).then(r => r.data),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["me", "asks"] }); },
  });
}
