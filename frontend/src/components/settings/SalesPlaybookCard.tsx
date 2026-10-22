"use client";
// Settings > AI: the sales playbook (GET/PUT /ai/sales-playbook) -- how the AI sells: the opening line, qualification questions,
// answers to common objections, the follow-up style and a few house rules. It shapes the AI's replies and follow-up drafts; it
// never lets the AI state a price the data does not give. Managers read; only the owner saves (audited).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { BTN_PRIMARY, INPUT, LABEL } from "@/components/quotes/ui";

export type Playbook = {
  opening_line: string; qualification_questions: string[]; never_ask_budget_first: boolean; objection_answers: Record<string, string>;
  follow_up_style: string; never_say_no: boolean; add_value_before_discount: boolean; rules: string[];
};

const lines = (s: string) => s.split("\n").map(l => l.trim()).filter(Boolean);
export const toObjections = (s: string): Record<string, string> =>
  Object.fromEntries(lines(s).map(l => l.split("|")).filter(p => p.length >= 2).map(([k, ...v]) => [k.trim(), v.join("|").trim()]));
const fromObjections = (o: Record<string, string>) => Object.entries(o).map(([k, v]) => `${k} | ${v}`).join("\n");

export function SalesPlaybookCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const isOwner = (session?.user as { role?: string } | undefined)?.role === "owner";
  const { data, isPending, isError } = useQuery<{ playbook: Playbook; empty: boolean }>({
    queryKey: ["ai-sales-playbook"],
    queryFn: () => api.get("/ai/sales-playbook").then(r => r.data),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const [f, setF] = useState({ opening: "", questions: "", objections: "", style: "", rules: "", budget: true, noNo: false, value: false });
  useEffect(() => {
    if (!data) return;
    const p = data.playbook;
    setF({ opening: p.opening_line, questions: p.qualification_questions.join("\n"), objections: fromObjections(p.objection_answers),
      style: p.follow_up_style, rules: p.rules.join("\n"), budget: p.never_ask_budget_first, noNo: p.never_say_no, value: p.add_value_before_discount });
  }, [data]);
  const save = useMutation({
    mutationFn: () => api.put("/ai/sales-playbook", {
      opening_line: f.opening, qualification_questions: lines(f.questions), never_ask_budget_first: f.budget,
      objection_answers: toObjections(f.objections), follow_up_style: f.style, never_say_no: f.noNo,
      add_value_before_discount: f.value, rules: lines(f.rules),
    }).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "Sales playbook saved" }); qc.invalidateQueries({ queryKey: ["ai-sales-playbook"] }); },
    onError: () => toast({ variant: "error", title: "Couldn't save", description: "Keep each line under 300 characters. Only the owner can change this." }),
  });

  if (isPending) {
    return <Card><CardBody className="flex items-center gap-2 text-sm text-[var(--haip-fg-subtle)]"><Loader2 size={14} className="animate-spin" /> Loading the sales playbook…</CardBody></Card>;
  }
  if (isError || !data) {
    return <Card><CardBody className="text-sm text-[var(--haip-fg-subtle)]">The sales playbook is visible to the owner and managers.</CardBody></Card>;
  }
  const off = !isOwner;
  const area = (id: string, label: string, value: string, key: keyof typeof f, h = "h-20") => (
    <div><label className={LABEL} htmlFor={id}>{label}</label>
      <textarea id={id} className={cn(INPUT, h, "py-2")} value={value} disabled={off} onChange={e => setF({ ...f, [key]: e.target.value })} /></div>
  );
  const box = (label: string, key: "budget" | "noNo" | "value") => (
    <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg)]">
      <input type="checkbox" checked={f[key]} disabled={off} onChange={e => setF({ ...f, [key]: e.target.checked })} className="accent-primary" />{label}
    </label>
  );

  return (
    <Card>
      <CardHeader title="Sales playbook" description={data.empty ? "Not set: the AI uses its standard way of replying." : "How the AI sells for you. It never states a price your data does not give."} />
      <CardBody className="space-y-3">
        {area("pb-open", "Opening line (lead with the experience)", f.opening, "opening")}
        {area("pb-q", "Qualification questions (one per line)", f.questions, "questions", "h-32")}
        {area("pb-obj", "Objections (one per line: objection | answer)", f.objections, "objections", "h-28")}
        {area("pb-style", "Follow-up style", f.style, "style")}
        {area("pb-rules", "House rules (one per line)", f.rules, "rules", "h-28")}
        {box("Never open by asking the budget", "budget")}
        {box("Never give a flat no: the team checks and comes back with the best option", "noNo")}
        {box("Offer added value (a kit or experience) before any discount", "value")}
        {isOwner && (
          <button type="button" className={BTN_PRIMARY} disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save"}
          </button>
        )}
      </CardBody>
    </Card>
  );
}
