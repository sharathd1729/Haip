import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  rentalwiseService,
  type RWThreadFilters,
  type RWBookingFilters,
  type RWBookingsResponse,
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

// ─── Local (HAIP-native) bookings ──────────────────────────────────────────────
// Bookings created directly in HAIP -- e.g. a Leads360 lead moved to a
// closed_won ("Sold") stage -- independent of any RentalWise integration.
// Same response shape as RWBookingsResponse so the Bookings table can render
// either source (or both, merged) without a separate component.

export function useLocalBookings(filters: RWBookingFilters = {}) {
  return useQuery({
    queryKey: ["local-bookings", filters],
    queryFn: () =>
      api.get<RWBookingsResponse>("/bookings", {
        params: {
          search: filters.search || undefined,
          status: filters.status || undefined,
          channel: filters.channel || undefined,
          sort: filters.sort,
          page: filters.page,
          per_page: filters.per_page,
          // Backend param names are date_from/date_to (bookings.py) --
          // reusing check_in_from/to here just to keep one filter-field
          // vocabulary across both the RentalWise proxy path and this one.
          date_from: filters.check_in_from || undefined,
          date_to: filters.check_in_to || undefined,
        },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: 1,
  });
}
