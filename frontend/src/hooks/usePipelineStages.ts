"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

// Leads360 restructure Phase 1: real CRUD over /pipeline-stages, replacing
// the old rename-only /tenants/me/pipeline-config blob. usePipelineConfig
// (legacy) still exists and still drives the leads board's stage tabs for
// now -- migrating the board itself to stage_id is a separate ticket.

export interface PipelineStageRow {
  id: string;
  key: string;
  label: string;
  color: string;
  order: number;
  is_default_entry: boolean;
  is_closed_won: boolean;
  is_closed_lost: boolean;
  lead_count: number;
}

export function usePipelineStages() {
  return useQuery<PipelineStageRow[]>({
    queryKey: ["pipeline-stages"],
    queryFn: async () => {
      const res = await api.get("/pipeline-stages");
      return (res.data as PipelineStageRow[]).sort((a, b) => a.order - b.order);
    },
    staleTime: 60_000,
  });
}

export function useInvalidatePipelineStages() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["pipeline-stages"] });
    qc.invalidateQueries({ queryKey: ["pipeline-config"] });
    qc.invalidateQueries({ queryKey: ["leads"] });
  };
}

export async function createPipelineStage(body: {
  key: string; label: string; color: string; is_closed_won?: boolean; is_closed_lost?: boolean;
}) {
  const res = await api.post("/pipeline-stages", body);
  return res.data as PipelineStageRow;
}

export async function updatePipelineStage(id: string, patch: Partial<{
  label: string; color: string; order: number;
  is_default_entry: boolean; is_closed_won: boolean; is_closed_lost: boolean;
}>) {
  const res = await api.patch(`/pipeline-stages/${id}`, patch);
  return res.data as PipelineStageRow;
}

export async function reorderPipelineStages(stageIdsInOrder: string[]) {
  const res = await api.put("/pipeline-stages/reorder", { stage_ids_in_order: stageIdsInOrder });
  return res.data as PipelineStageRow[];
}

export async function deletePipelineStage(id: string, reassignToStageId?: string) {
  await api.delete(`/pipeline-stages/${id}`, {
    data: { reassign_to_stage_id: reassignToStageId ?? null },
  });
}
