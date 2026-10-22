"use client";
// Settings > AI: "Who may decide what" (GET/PUT /ai/agent-policy). Per action, the owner picks whether the AI does it alone, prepares
// it for a person to approve, or asks a person first (Ask a manager). The server enforces it in the reply path and the sales agent,
// and a policy never loosens a safety check. Managers can read; only the owner saves (audited).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { BTN_PRIMARY, INPUT } from "@/components/quotes/ui";

type Mode = "autonomous" | "draft_for_approval" | "consult";
export type AgentPolicy = { modes: Record<string, Mode>; defaults: Record<string, Mode>; classes: { key: string; label: string }[] };

const MODE_LABEL: Record<Mode, string> = {
  autonomous: "AI does it",
  draft_for_approval: "AI drafts, a person approves",
  consult: "Ask a person first",
};

export function AgentPolicyCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const isOwner = (session?.user as { role?: string } | undefined)?.role === "owner";
  const { data, isPending, isError } = useQuery<AgentPolicy>({
    queryKey: ["ai-agent-policy"],
    queryFn: () => api.get("/ai/agent-policy").then(r => r.data),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const [modes, setModes] = useState<Record<string, Mode>>({});
  useEffect(() => { if (data) setModes(data.modes); }, [data]);
  const save = useMutation({
    mutationFn: (changed: Record<string, Mode>) => api.put("/ai/agent-policy", { modes: changed }).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "AI policy saved" }); qc.invalidateQueries({ queryKey: ["ai-agent-policy"] }); },
    onError: () => toast({ variant: "error", title: "Couldn't save", description: "Only the owner can change the AI policy." }),
  });

  if (isPending) {
    return <Card><CardBody className="flex items-center gap-2 text-sm text-[var(--haip-fg-subtle)]"><Loader2 size={14} className="animate-spin" /> Loading the AI policy…</CardBody></Card>;
  }
  if (isError || !data) {
    return <Card><CardBody className="text-sm text-[var(--haip-fg-subtle)]">The AI policy is visible to the owner and managers.</CardBody></Card>;
  }
  const changed = Object.fromEntries(Object.entries(modes).filter(([k, v]) => data.modes[k] !== v));

  return (
    <Card>
      <CardHeader title="Who may decide what" description="What the AI may do alone. Safety checks (prices, availability, refunds) always apply." />
      <CardBody className="space-y-2">
        <ul className="divide-y divide-[var(--haip-border)]">
          {data.classes.map(c => (
            <li key={c.key} className="flex flex-col gap-2 py-2 sm:flex-row sm:items-center sm:justify-between">
              <span className="min-w-0 text-sm text-[var(--haip-fg)]">
                {c.label}
                {modes[c.key] !== data.defaults[c.key] && <span className="ml-2"><StatusPill tone="info">Changed from default</StatusPill></span>}
              </span>
              <select aria-label={c.label} className={`${INPUT} sm:w-64`} value={modes[c.key] ?? data.defaults[c.key]} disabled={!isOwner}
                onChange={e => setModes({ ...modes, [c.key]: e.target.value as Mode })}>
                {(Object.keys(MODE_LABEL) as Mode[]).map(m => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
              </select>
            </li>
          ))}
        </ul>
        {isOwner && (
          <button type="button" className={BTN_PRIMARY} disabled={!Object.keys(changed).length || save.isPending} onClick={() => save.mutate(changed)}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save"}
          </button>
        )}
      </CardBody>
    </Card>
  );
}
