"use client";
// "Send to": the chosen lead (with what will happen to its stage), or a search by name or phone. A number nobody has gets
// "Add as new lead" (phone, optional name, where they came from); the server reuses the person if HAIP already knows the
// number (a mirrored WhatsApp chat, an Instagram guest), never a duplicate.
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Search } from "@/lib/icons";
import api from "@/lib/api";
import { StatusPill } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { BTN, BTN_GHOST, BTN_PRIMARY, Field, INPUT, apiProblems } from "../ui";
import { useDebounced } from "./useDebounced";
import { SOURCE_LABEL, stageNote } from "./calcHelpers";
import type { AddOffer, LeadRow, LeadSearch, LeadSource } from "./types";

export function SendTo({ lead, onLead, sources, initialText = "", initialAdd = null }: {
  lead: LeadRow | null; onLead: (lead: LeadRow | null) => void; sources: LeadSource[]; initialText?: string; initialAdd?: AddOffer | null;
}) {
  const [text, setText] = useState(initialText);
  const [adding, setAdding] = useState<AddOffer | null>(initialAdd);
  const q = useDebounced(text.trim(), 250);
  const hits = useQuery<LeadSearch>({
    queryKey: ["quote-calc-leads", q], queryFn: () => api.get("/quote-calculator/leads", { params: { q } }).then(r => r.data),
    enabled: !lead && !adding && q.length > 0, staleTime: 15_000, retry: 0,
  });

  if (lead) {
    return (
      <div className="flex items-start justify-between gap-2.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-surface)] px-3 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-[14px]"><strong>{lead.guest_name}</strong>
            <span className="text-[var(--haip-fg-subtle)]">{lead.phone_last4 ? ` · ••${lead.phone_last4}` : ""} · {lead.source_label}</span>
          </p>
          <p className="mt-0.5 text-[12.5px] text-[var(--haip-fg-subtle)]">{stageNote(lead)}</p>
        </div>
        <button type="button" className={BTN_GHOST} onClick={() => { onLead(null); setText(""); }}>Change</button>
      </div>
    );
  }
  if (adding) {
    return <NewLead offer={adding} sources={sources} onCancel={() => setAdding(null)} onAdded={l => { setAdding(null); onLead(l); }} />;
  }
  const data = hits.data;
  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
        <input id="calc-to" type="search" value={text} placeholder="Search name or phone" autoComplete="off"
          onChange={e => setText(e.target.value)} className={cn(INPUT, "pl-9")} />
      </div>
      {!q ? (
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Type a name or phone number.</p>
      ) : hits.isLoading ? (
        <p className="flex items-center gap-2 text-[12.5px] text-[var(--haip-fg-subtle)]"><Loader2 size={13} className="animate-spin" /> Searching…</p>
      ) : hits.isError ? (
        <p className="text-[12.5px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t search leads. <button type="button" className="underline" onClick={() => hits.refetch()}>Try again</button></p>
      ) : (
        <ul className="grid gap-1.5" aria-label="Leads">
          {(data?.results ?? []).map(r => (
            <li key={r.inquiry_id}>
              <button type="button" onClick={() => onLead(r)}
                className="flex min-h-11 w-full flex-wrap items-center justify-between gap-x-2.5 gap-y-1 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-left text-[14px] hover:border-primary">
                <span className="min-w-0"><strong>{r.guest_name}</strong>
                  <span className="text-[var(--haip-fg-subtle)]">{r.phone_last4 ? ` · ••${r.phone_last4}` : ""} · {r.source_label}</span>
                </span>
                <StatusPill tone={r.open ? "success" : "warning"}>{r.open ? "Open" : "Closed"} · {r.stage_label}</StatusPill>
              </button>
            </li>
          ))}
          {data && !data.results.length && (data.add ? (
            <li>
              <button type="button" onClick={() => setAdding(data.add)}
                className="flex min-h-11 w-full flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-left text-[14px] hover:border-primary">
                <span>{data.add.known ? <><strong>{data.add.known_name || "Someone"}</strong> is in HAIP with this number, no lead yet</> : "No one in HAIP has this number"}</span>
                <StatusPill tone="success">Add as new lead</StatusPill>
              </button>
            </li>
          ) : (
            <li className="text-[12.5px] text-[var(--haip-fg-subtle)]">No lead matches. Type the full phone number to add a new lead.</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NewLead({ offer, sources, onCancel, onAdded }: {
  offer: AddOffer; sources: LeadSource[]; onCancel: () => void; onAdded: (l: LeadRow) => void;
}) {
  const [phone, setPhone] = useState(offer.phone ?? "");
  const [name, setName] = useState(offer.known_name ?? "");
  const [source, setSource] = useState<LeadSource>("whatsapp");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setPhone(offer.phone ?? ""); setName(offer.known_name ?? ""); }, [offer]);
  const add = useMutation({
    mutationFn: () => api.post("/quote-calculator/leads", { phone, name: name.trim() || null, source }).then(r => r.data as LeadRow),
    onSuccess: onAdded,
    onError: e => setError(apiProblems(e).message),
  });
  return (
    <div className="space-y-2.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-surface)] p-3">
      <h3 className="font-[family-name:var(--font-display)] text-[15px] font-semibold">Add as new lead</h3>
      <div className="grid grid-cols-1 gap-2.5 min-[420px]:grid-cols-3">
        <Field label="Phone" htmlFor="nl-phone"><input id="nl-phone" className={cn(INPUT, "num")} inputMode="tel" value={phone} onChange={e => setPhone(e.target.value)} /></Field>
        <Field label="Name (optional)" htmlFor="nl-name"><input id="nl-name" className={INPUT} value={name} maxLength={120} onChange={e => setName(e.target.value)} /></Field>
        <Field label="Came from" htmlFor="nl-src">
          <select id="nl-src" className={INPUT} value={source} onChange={e => setSource(e.target.value as LeadSource)}>
            {sources.map(s => <option key={s} value={s}>{SOURCE_LABEL[s] ?? s}</option>)}
          </select>
        </Field>
      </div>
      <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
        {offer.known ? "This number is already in HAIP. The lead is added to that same person, no duplicate." : "New person. The phone number makes them a counted lead."}
      </p>
      {error && <p role="alert" className="text-[12.5px] text-[var(--haip-status-danger-fg)]">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={BTN_PRIMARY} disabled={add.isPending || phone.replace(/\D/g, "").length < 6} onClick={() => { setError(null); add.mutate(); }}>
          {add.isPending ? <Loader2 size={14} className="animate-spin" /> : "Add lead"}
        </button>
        <button type="button" className={BTN} onClick={onCancel}>Back to search</button>
      </div>
    </div>
  );
}
