"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

export interface PipelineStage {
  key: string;
  label: string;
  color: string;
  visible: boolean;
  order: number;
}

export const DEFAULT_PIPELINE_STAGES: PipelineStage[] = [
  { key: "new",                  label: "New",        color: "#6366f1", visible: true, order: 0 },
  { key: "responding",           label: "Responding", color: "#f59e0b", visible: true, order: 1 },
  { key: "quoted",               label: "Quoted",     color: "#8b5cf6", visible: true, order: 2 },
  { key: "site_visit_scheduled", label: "Site Visit", color: "#06b6d4", visible: true, order: 3 },
  { key: "site_visit_done",      label: "Visit Done", color: "#10b981", visible: true, order: 4 },
  { key: "booked",               label: "Booked",     color: "#22c55e", visible: true, order: 5 },
  { key: "closed",               label: "Closed",     color: "#6b7280", visible: true, order: 6 },
];

export function usePipelineConfig() {
  return useQuery<PipelineStage[]>({
    queryKey: ["pipeline-config"],
    queryFn: async () => {
      const res = await api.get("/tenants/me/pipeline-config");
      return (res.data.stages as PipelineStage[]).sort((a, b) => a.order - b.order);
    },
    staleTime: 5 * 60_000,
    placeholderData: DEFAULT_PIPELINE_STAGES,
  });
}

export function useInvalidatePipelineConfig() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["pipeline-config"] });
}
