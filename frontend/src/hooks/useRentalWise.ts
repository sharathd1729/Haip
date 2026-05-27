import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  rentalwiseService,
  type RWThreadFilters,
  type RWBookingFilters,
  type RWSendMessagePayload,
} from "@/lib/rentalwise";

// ─── Threads ──────────────────────────────────────────────────────────────────

export function useRWThreads(filters: RWThreadFilters = {}) {
  return useQuery({
    queryKey:    ["rw-threads", filters],
    queryFn:     () => rentalwiseService.getThreads(filters),
    placeholderData: keepPreviousData,
    staleTime:   30_000,
    retry:       1,
  });
}

// ─── Thread messages ──────────────────────────────────────────────────────────

export function useRWThreadMessages(threadId: number | null) {
  return useQuery({
    queryKey: ["rw-thread-messages", threadId],
    queryFn:  () => rentalwiseService.getThreadMessages(threadId!),
    enabled:  !!threadId,
    staleTime: 15_000,
    retry:     1,
  });
}

// ─── Send message mutation ────────────────────────────────────────────────────

export function useSendRWMessage(threadId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RWSendMessagePayload) => rentalwiseService.sendMessage(payload),
    onSuccess: () => {
      // Invalidate the messages cache so the new message appears immediately
      if (threadId) {
        qc.invalidateQueries({ queryKey: ["rw-thread-messages", threadId] });
      }
      // Also refresh the thread list so the last_message_excerpt updates
      qc.invalidateQueries({ queryKey: ["rw-threads"] });
    },
  });
}

// ─── Bookings ─────────────────────────────────────────────────────────────────

export function useRWBookings(filters: RWBookingFilters = {}) {
  return useQuery({
    queryKey:    ["rw-bookings", filters],
    queryFn:     () => rentalwiseService.getBookings(filters),
    placeholderData: keepPreviousData,
    staleTime:   30_000,
    retry:       1,
  });
}
