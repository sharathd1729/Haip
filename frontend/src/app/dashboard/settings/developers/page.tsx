"use client";
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page";
import { errorMessage, fmtDate } from "@/lib/bookings";
import { WebhooksSection } from "@/components/developers/WebhooksSection";

interface ApiKeyRow {
  id: string; name: string; prefix: string; scopes: string[]; created_at: string | null;
  last_used_at: string | null; expires_at: string | null; revoked: boolean;
}
interface KeysResponse {
  keys: ApiKeyRow[];
  scopes: { scope: string; description: string }[];
  docs_url: string;
  openapi_url: string;
}
interface Created extends ApiKeyRow { key: string }

const field = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary";
const EXPIRY = [
  { value: "", label: "Never expires" }, { value: "90", label: "90 days" }, { value: "365", label: "1 year" },
];

export default function DevelopersPage() {
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [expiry, setExpiry] = useState("");
  const [fresh, setFresh] = useState<Created | null>(null);

  const { data, isLoading } = useQuery<KeysResponse>({
    queryKey: ["api-keys"],
    queryFn: () => api.get("/api-keys").then(r => r.data),
  });

  const create = useMutation({
    mutationFn: () => api.post<Created>("/api-keys", { name: name.trim(), scopes, expires_in_days: expiry ? Number(expiry) : undefined }),
    onSuccess: res => {
      setFresh(res.data); setName(""); setScopes([]); setExpiry("");
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not create the key") }),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`/api-keys/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["api-keys"] }); toast({ variant: "success", title: "Key revoked" }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not revoke the key") }),
  });

  const copy = (text: string) =>
    navigator.clipboard?.writeText(text).then(
      () => toast({ variant: "success", title: "Copied" }),
      () => toast({ variant: "error", title: "Could not copy. Select it and copy by hand." }),
    );

  const toggle = (s: string) => setScopes(cur => (cur.includes(s) ? cur.filter(x => x !== s) : [...cur, s]));
  const active = (data?.keys ?? []).filter(k => !k.revoked);
  const base = data?.docs_url.replace(/\/docs$/, "") ?? "https://api.genhaip.com/api/public/v1";

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <PageHeader title="Developers" subtitle="API keys and documentation to connect your own systems to HAIP" />

      <div className="haip-card p-4 space-y-3">
        <p className="text-sm font-semibold text-[var(--haip-fg)]">API documentation</p>
        <p className="text-xs text-[var(--haip-fg-subtle)]">
          Read bookings and send WhatsApp and Instagram messages from your own software. Share these links with the team building the integration.
        </p>
        <div className="flex flex-wrap gap-2">
          {data && (
            <>
              <a href={data.docs_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs font-semibold bg-primary text-white px-3 py-2 rounded-lg hover:bg-primary">
                Open documentation <ExternalLink size={12} />
              </a>
              <a href={data.openapi_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs font-semibold border border-[var(--haip-border)] px-3 py-2 rounded-lg hover:bg-[var(--haip-surface)]">
                OpenAPI file (Postman, code generators)
              </a>
              <button onClick={() => copy(data.docs_url)} className="inline-flex items-center gap-1.5 text-xs font-semibold border border-[var(--haip-border)] px-3 py-2 rounded-lg hover:bg-[var(--haip-surface)]">
                <Copy size={12} /> Copy docs link
              </button>
            </>
          )}
        </div>
        <pre className="text-[11px] leading-relaxed bg-gray-900 text-gray-100 rounded-lg p-3 overflow-x-auto">{`curl ${base}/bookings \\
  -H "Authorization: Bearer YOUR_API_KEY"`}</pre>
      </div>

      {fresh && (
        <div className="haip-card p-4 space-y-3 border-amber-200">
          <p className="text-sm font-semibold text-[var(--haip-fg)]">Copy your key now, it won&apos;t be shown again</p>
          <div className="flex gap-2">
            <input readOnly value={fresh.key} onFocus={e => e.currentTarget.select()} className="flex-1 min-w-0 text-xs font-mono bg-[var(--haip-surface)] border border-[var(--haip-border)] rounded-lg px-2.5 py-2" />
            <button onClick={() => copy(fresh.key)} className="flex items-center gap-1 text-xs font-semibold border border-[var(--haip-border)] px-3 rounded-lg hover:bg-[var(--haip-surface)]"><Copy size={12} /> Copy</button>
          </div>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Store it on your server as a secret. Anyone with this key can use the access it grants. If it leaks, revoke it below.</p>
          <button onClick={() => setFresh(null)} className="text-xs font-semibold text-primary hover:underline">I have saved it</button>
        </div>
      )}

      {isLoading ? <Skeleton className="h-40 rounded-xl" /> : (
        <>
          <div className="haip-card">
            <div className="haip-card-head"><h2 className="haip-card-title">API keys</h2></div>
            <div className="divide-y divide-[var(--haip-border)]">
              {active.length === 0 && <p className="p-4 text-sm text-[var(--haip-fg-subtle)]">No API keys yet.</p>}
              {active.map(k => (
                <div key={k.id} className="p-4 flex items-start gap-3">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p className="text-sm font-semibold text-[var(--haip-fg)]">{k.name} <span className="font-mono text-xs font-normal text-[var(--haip-fg-subtle)]">{k.prefix}...</span></p>
                    <div className="flex flex-wrap gap-1">
                      {k.scopes.map(s => <span key={s} className="text-[11px] font-mono bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)] rounded px-1.5 py-0.5">{s}</span>)}
                    </div>
                    <p className="text-xs text-[var(--haip-fg-subtle)]">
                      Created {fmtDate(k.created_at)} · {k.last_used_at ? `last used ${fmtDate(k.last_used_at)}` : "never used"}
                      {k.expires_at ? ` · expires ${fmtDate(k.expires_at)}` : ""}
                    </p>
                  </div>
                  {isOwner && (
                    <button
                      aria-label={`Revoke ${k.name}`}
                      onClick={() => { if (confirm(`Revoke "${k.name}"? Anything using it stops working immediately.`)) revoke.mutate(k.id); }}
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--haip-fg-subtle)] hover:text-red-500 hover:bg-red-50"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {isOwner ? (
            <div className="haip-card p-4 space-y-4">
              <p className="text-sm font-semibold text-[var(--haip-fg)]">Create an API key</p>
              <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)]">Name
                <input className={cn(field, "mt-1")} placeholder="e.g. Ratha operations platform" value={name} onChange={e => setName(e.target.value)} maxLength={100} />
              </label>
              <fieldset className="space-y-2">
                <legend className="text-xs font-semibold text-[var(--haip-fg-subtle)] mb-1">What can this key do?</legend>
                {(data?.scopes ?? []).map(s => (
                  <label key={s.scope} className="flex items-start gap-2.5 text-sm cursor-pointer">
                    <input type="checkbox" checked={scopes.includes(s.scope)} onChange={() => toggle(s.scope)} className="mt-1 h-4 w-4 rounded border-[var(--haip-border-strong)] text-primary focus:ring-primary" />
                    <span><span className="font-mono text-xs text-[var(--haip-fg)]">{s.scope}</span><span className="block text-xs text-[var(--haip-fg-subtle)]">{s.description}</span></span>
                  </label>
                ))}
              </fieldset>
              <label className="block text-xs font-semibold text-[var(--haip-fg-subtle)]">Expiry
                <select className={cn(field, "mt-1")} value={expiry} onChange={e => setExpiry(e.target.value)}>
                  {EXPIRY.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </label>
              <button
                onClick={() => create.mutate()}
                disabled={!name.trim() || scopes.length === 0 || create.isPending}
                className="text-sm font-semibold bg-primary hover:bg-primary disabled:opacity-40 text-white px-4 py-2 rounded-lg"
              >
                {create.isPending ? "Creating..." : "Create key"}
              </button>
            </div>
          ) : (
            <p className="text-xs text-[var(--haip-fg-subtle)]">Only the account owner can create or revoke API keys.</p>
          )}
        </>
      )}

      <WebhooksSection isOwner={isOwner} />
    </div>
  );
}
