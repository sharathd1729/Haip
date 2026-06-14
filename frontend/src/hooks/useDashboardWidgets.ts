import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

export interface WidgetSnapshot {
  key: string;
  title: string;
  state: "unavailable" | "early_signal" | "full_insight";
  summary: string | null;
  data: Record<string, unknown> | null;
  generated_at: string | null;
  next_refresh_at: string | null;
}

export interface DashboardWidgetsResponse {
  widgets: WidgetSnapshot[];
  available_modules: string[];
}

export interface LibraryWidget {
  key: string;
  title: string;
  description: string;
  category: string;
  state: string;
  required_modules: string[];
  missing_modules: string[];
}

export function useDashboardWidgets(rangeDays = 30) {
  return useQuery<DashboardWidgetsResponse>({
    queryKey: ["dashboard-widgets", rangeDays],
    queryFn: () =>
      api
        .get("/dashboard/widgets", { params: { range_days: rangeDays } })
        .then((r) => r.data),
    staleTime: 4 * 60_000,
    refetchInterval: 10 * 60_000,
  });
}

export function useWidgetLibrary() {
  return useQuery<{ library: LibraryWidget[] }>({
    queryKey: ["widget-library"],
    queryFn: () => api.get("/dashboard/widget-library").then((r) => r.data),
    staleTime: 5 * 60_000,
  });
}

export function useInvalidateDashboardWidgets() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["dashboard-widgets"] });
}
