import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  rentalwiseService,
  type RWThreadFilters,
  type RWBookingFilters,
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
