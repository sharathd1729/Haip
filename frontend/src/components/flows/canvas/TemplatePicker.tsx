"use client";
// A flow "template" block (flow_engine._send_flow_template): an approved template, sent even outside the 24-hour window.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { VariableMapping, defaultMap, type VariableMap } from "@/components/messaging/VariableMapping";
import type { Template } from "@/components/messaging/templateModel";
import type { NodeData } from "./flowModel";

type Row = Template & { id: string; name: string; status: string };

export function TemplatePicker({ data, onChange, inputCls }: { data: NodeData; onChange: (patch: Partial<NodeData>) => void; inputCls: string }) {
  const { data: templates = [], isLoading, isError, refetch } = useQuery<Row[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data),
    staleTime: 60_000,
  });
  const approved = templates.filter(t => t.status === "approved");
  const picked = approved.find(t => t.id === data.template_id);
  if (isLoading) return <p className="text-sm text-[var(--haip-fg-subtle)]">Loading templates...</p>;
  if (isError) return (
    <p className="text-sm text-[var(--haip-status-danger-fg)]">
      Couldn&apos;t load templates. <button type="button" className="font-semibold underline" onClick={() => refetch()}>Try again</button>
    </p>
  );
  if (!approved.length) return <p className="text-sm text-[var(--haip-fg-subtle)]">No approved templates yet. Create one under WhatsApp templates first.</p>;
  return (
    <div className="space-y-3">
      <select value={data.template_id ?? ""} aria-label="Approved template" className={inputCls}
        onChange={e => { const t = approved.find(x => x.id === e.target.value); onChange({ template_id: e.target.value || undefined, variable_map: defaultMap(t) as Record<string, unknown> }); }}>
        <option value="">Choose a template</option>
        {approved.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <p className="text-[12px] text-[var(--haip-fg-subtle)]">Templates reach the guest even after the 24-hour window, unlike a plain message.</p>
      {picked && <VariableMapping template={picked} value={(data.variable_map ?? {}) as VariableMap}
        onChange={(m: VariableMap) => onChange({ variable_map: m as Record<string, unknown> })} />}
    </div>
  );
}
