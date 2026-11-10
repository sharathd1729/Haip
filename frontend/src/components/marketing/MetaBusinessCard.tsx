"use client";
// The workspace's Meta Business connection: one System User token for ad results, lead forms and, if the owner chooses, Instagram messages.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { ago, errorText } from "./ads";

type Capability = { ok: boolean; missing: string[] };
type UseKey = "ads" | "lead_forms" | "instagram_dm";
export type MetaBusiness = {
  connected: boolean; token_name: string | null; capabilities: Record<UseKey, Capability> | null;
  pages: { id: string; name: string }[]; page: { id: string; name: string | null } | null;
  checked_at: string | null; token_expires_at: string | null;
  lead_forms: { enabled: boolean; forms: { id: string; name: string; status: string }[]; last_run_at: string | null;
    last_error: string | null; imported: number; last_lead_at: string | null };
  instagram: { mode: "meta_business" | "instagram_login" | null; username: string | null; webhook_subscribed: boolean };
};

const USES: { key: UseKey; label: string }[] = [
  { key: "ads", label: "Ad spend and results" },
  { key: "lead_forms", label: "Lead forms" },
  { key: "instagram_dm", label: "Instagram messages" },
];
const primary = "h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50";
const quiet = "h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 text-sm font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50";
const field = "h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base text-[var(--haip-fg)]";

export function MetaBusinessCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [token, setToken] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [sureRemove, setSureRemove] = useState(false);
  const [secret, setSecret] = useState("");
  const [switching, setSwitching] = useState(false);
  const status = useQuery<MetaBusiness>({ queryKey: ["meta-business"], queryFn: () => api.get("/meta-business").then(r => r.data) });

  const change = useMutation({
    mutationFn: (run: () => Promise<{ data: MetaBusiness }>) => run().then(r => r.data),
    onSuccess: data => {
      qc.setQueryData(["meta-business"], data);
      qc.invalidateQueries({ queryKey: ["ads-status"] });
      qc.invalidateQueries({ queryKey: ["ads-accounts"] });
      setToken(""); setReplacing(false); setSureRemove(false); setSecret(""); setSwitching(false);
    },
    onError: e => toast({ variant: "error", title: "That did not work", description: errorText(e, "Try again.") }),
  });
  const importOld = useMutation({
    mutationFn: () => api.post("/meta-business/lead-forms/import", { days: 90 }).then(r => r.data),
    onSuccess: () => toast({ variant: "success", title: "Import started", description: "Leads from the last 90 days will appear in Leads over the next few minutes." }),
    onError: e => toast({ variant: "error", title: "Could not start the import", description: errorText(e, "Try again.") }),
  });

  const s = status.data;
  const tokenForm = (
    <form className="space-y-2" onSubmit={e => { e.preventDefault(); change.mutate(() => api.put("/meta-business/token", { access_token: token.trim() })); }}>
      <label className="block text-sm font-semibold text-[var(--haip-fg)]" htmlFor="meta-business-token">Meta Business token</label>
      <input id="meta-business-token" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} className={field}
        placeholder="Starts with EAA…" />
      <p className="text-xs text-[var(--haip-fg-subtle)]">Meta Business Settings → Users → System users → Generate new token. HAIP checks it with Meta, stores it encrypted and never shows it again.</p>
      <button type="submit" disabled={token.trim().length < 20 || change.isPending} className={primary}>{change.isPending ? "Checking with Meta…" : "Connect"}</button>
    </form>
  );

  return (
    <Card>
      <CardHeader title="Meta Business connection" description="One token from your Meta Business account. HAIP uses it to read ad results and bring in lead-form leads. Nothing is changed in Meta." />
      <CardBody className="space-y-4">
        {status.isLoading && <Skeleton className="h-24 w-full" />}
        {status.isError && <p role="alert" className="text-sm text-[var(--haip-status-danger-fg)]">{errorText(status.error, "Could not load the Meta connection.")}</p>}
        {s && !s.connected && tokenForm}
        {s?.connected && (
          <>
            <p className="text-sm text-[var(--haip-fg-2)]">
              Connected as <span className="font-semibold text-[var(--haip-fg)]">{s.token_name || "a system user"}</span> · checked {ago(s.checked_at)} ·{" "}
              {s.token_expires_at ? `token ends ${new Date(s.token_expires_at).toLocaleDateString("en-IN")}` : "token does not expire"}
            </p>
            <ul className="space-y-2">
              {USES.map(u => {
                const c = s.capabilities?.[u.key];
                return (
                  <li key={u.key} className="flex flex-wrap items-start gap-x-3 gap-y-1 text-sm">
                    <span className="min-w-[10rem] font-semibold text-[var(--haip-fg)]">{u.label}</span>
                    <StatusPill tone={c?.ok ? "success" : "warning"}>{c?.ok ? "Ready" : "Not ready"}</StatusPill>
                    {!c?.ok && c?.missing.length ? <span className="w-full text-xs text-[var(--haip-fg-subtle)]">Missing: {c.missing.join("; ")}</span> : null}
                  </li>
                );
              })}
            </ul>
            {s.pages.length > 1 && (
              <label className="block text-sm font-semibold text-[var(--haip-fg)]">Facebook page
                <select className={`${field} mt-1`} value={s.page?.id ?? ""} disabled={change.isPending}
                  onChange={e => { const page_id = e.target.value; change.mutate(() => api.put("/meta-business/page", { page_id })); }}>
                  <option value="" disabled>Choose a page</option>
                  {s.pages.map(p => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}
                </select>
              </label>
            )}
            {s.capabilities?.lead_forms.ok && (
              <div className="space-y-2 rounded-lg border border-[var(--haip-border)] p-3">
                <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-semibold text-[var(--haip-fg)]">
                  <input type="checkbox" role="switch" className="h-5 w-5 accent-primary" checked={s.lead_forms.enabled} disabled={change.isPending}
                    onChange={e => { const enabled = e.target.checked; change.mutate(() => api.put("/meta-business/lead-forms", { enabled })); }} />
                  Bring lead-form leads into HAIP{s.page?.name ? ` (${s.page.name})` : ""}
                </label>
                {s.lead_forms.enabled && (
                  <>
                    <p className="text-xs text-[var(--haip-fg-subtle)]">
                      Checked every 5 minutes · last check {ago(s.lead_forms.last_run_at)} · {s.lead_forms.imported} lead{s.lead_forms.imported === 1 ? "" : "s"} brought in so far
                    </p>
                    {s.lead_forms.last_error && <p role="alert" className="text-xs text-[var(--haip-status-danger-fg)]">Meta said: {s.lead_forms.last_error}</p>}
                    {s.lead_forms.forms.length > 0 && (
                      <ul className="flex flex-wrap gap-2">
                        {s.lead_forms.forms.map(f => <li key={f.id}><StatusPill tone={f.status === "ACTIVE" ? "success" : "neutral"}>{f.name || f.id}</StatusPill></li>)}
                      </ul>
                    )}
                    <button type="button" className={quiet} disabled={importOld.isPending} onClick={() => importOld.mutate()}>
                      {importOld.isPending ? "Starting…" : "Import the last 90 days"}
                    </button>
                  </>
                )}
              </div>
            )}
            {s.capabilities?.instagram_dm.ok && (
              <div className="space-y-2 rounded-lg border border-[var(--haip-border)] p-3">
                <p className="text-sm font-semibold text-[var(--haip-fg)]">Instagram messages</p>
                {s.instagram.mode === "meta_business" && (
                  <p className="text-xs text-[var(--haip-fg-2)]">
                    Running on this token{s.instagram.username ? ` (@${s.instagram.username})` : ""}.
                    {!s.instagram.webhook_subscribed && " Meta has not confirmed the page's message subscription. Save the App Secret again to retry."}
                  </p>
                )}
                {s.instagram.mode === "instagram_login" && (
                  <p className="text-xs text-[var(--haip-fg-2)]">
                    Connected with Instagram Login{s.instagram.username ? ` (@${s.instagram.username})` : ""}. It keeps working as it is; nothing to do here.
                  </p>
                )}
                {s.instagram.mode === "instagram_login" && !switching && (
                  <button type="button" className={quiet} onClick={() => setSwitching(true)}>Use this token instead</button>
                )}
                {(s.instagram.mode === null || switching || (s.instagram.mode === "meta_business" && !s.instagram.webhook_subscribed)) && (
                  <form className="space-y-2" onSubmit={e => { e.preventDefault(); const app_secret = secret.trim(); change.mutate(() => api.post("/meta-business/instagram", { app_secret })); }}>
                    <label className="block text-sm font-semibold text-[var(--haip-fg)]" htmlFor="meta-business-app-secret">App Secret of the Meta app this token belongs to</label>
                    <input id="meta-business-app-secret" type="password" autoComplete="off" value={secret} onChange={e => setSecret(e.target.value)} className={field} />
                    <p className="text-xs text-[var(--haip-fg-subtle)]">
                      Meta for Developers → your app → App settings → Basic. In that app, point the Instagram webhook at HAIP (the callback URL and verify token are in
                      Settings → Integrations → Instagram). The app must be Live with Advanced Access for instagram_manage_messages, or only people with a role on the app get replies.
                      The other way to connect is Instagram Login, on the Integrations page.
                    </p>
                    <button type="submit" disabled={secret.trim().length < 8 || change.isPending} className={primary}>
                      {change.isPending ? "Asking Meta…" : "Use this token for Instagram messages"}
                    </button>
                  </form>
                )}
              </div>
            )}
            {replacing ? tokenForm : (
              <div className="flex flex-wrap gap-2">
                <button type="button" className={quiet} disabled={change.isPending} onClick={() => change.mutate(() => api.post("/meta-business/recheck"))}>Check again</button>
                <button type="button" className={quiet} onClick={() => setReplacing(true)}>Replace token</button>
                <button type="button" className={quiet} disabled={change.isPending}
                  onClick={() => (sureRemove ? change.mutate(() => api.delete("/meta-business")) : setSureRemove(true))}>
                  {sureRemove ? "Tap again to remove" : "Remove"}
                </button>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
