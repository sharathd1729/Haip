"use client";
// The signed, view-only report link sent by email / WhatsApp (no login; the link names one recipient and lasts 7 days).
// Backend: GET /api/v1/public/analyst/{token} (+ /report.pdf); assigning a waiting lead needs a one-time code e-mailed to the
// recipient (POST .../assign/start then .../assign/confirm).
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { HealthChecks } from "@/components/analyst/HealthChecks";
import { DemandMoney, ReasonsPanels, TeamTable, WorkingPanels } from "@/components/analyst/BriefPanels";
import { KIND_LABEL, periodText, type Report } from "@/components/analyst/types";

const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;
const field = "min-h-[44px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] sm:text-sm";
const btn = "inline-flex min-h-[44px] items-center justify-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60";

interface PublicReport extends Report {
  viewer: { first_name: string; money: boolean };
  assign: { leads: { inquiry_id: string; who: string; severity?: string }[]; team: { user_id: string; name: string }[] };
}

async function post(url: string, body: unknown) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.detail?.message || "That didn't work. Try again.");
  return data;
}

function Assign({ token, data }: { token: string; data: PublicReport["assign"] }) {
  const [lead, setLead] = useState("");
  const [person, setPerson] = useState("");
  const [nonce, setNonce] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `${API}/public/analyst/${encodeURIComponent(token)}/assign`;
  if (!data.leads.length) return null;
  return (
    <Card>
      <CardHeader title="Leads waiting for an owner" description="Pick a lead and a person. We e-mail you a code to confirm." />
      <CardBody className="space-y-3">
        <select aria-label="Lead" className={field} value={lead} onChange={e => setLead(e.target.value)}>
          <option value="">Choose a lead…</option>
          {data.leads.map(l => <option key={l.inquiry_id} value={l.inquiry_id}>{l.who}{l.severity ? ` · ${l.severity}` : ""}</option>)}
        </select>
        <select aria-label="Person" className={field} value={person} onChange={e => setPerson(e.target.value)}>
          <option value="">Give it to…</option>
          {data.team.map(t => <option key={t.user_id} value={t.user_id}>{t.name}</option>)}
        </select>
        {nonce === null ? (
          <button type="button" className={btn} disabled={busy || !lead || !person} onClick={async () => {
            setBusy(true); setMsg(null);
            try { const r = await post(`${base}/start`, { inquiry_id: lead, user_id: person }); setNonce(r.nonce); setMsg("We e-mailed you a 6-digit code."); }
            catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
          }}>Send me a code</button>
        ) : (
          <div className="flex gap-2">
            <input aria-label="Code" inputMode="numeric" maxLength={6} className={field} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ""))} />
            <button type="button" className={btn} disabled={busy || code.length !== 6} onClick={async () => {
              setBusy(true);
              try { await post(`${base}/confirm`, { nonce, code }); setMsg("Assigned."); setNonce(null); setCode(""); setLead(""); }
              catch (e) { setMsg((e as Error).message); setNonce(null); setCode(""); } finally { setBusy(false); }
            }}>Confirm</button>
          </div>
        )}
        {msg && <p className="text-sm text-[var(--haip-fg-muted)]" role="status">{msg}</p>}
      </CardBody>
    </Card>
  );
}

export default function SignedReportPage() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<PublicReport | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "gone" | "error">("loading");
  useEffect(() => {
    fetch(`${API}/public/analyst/${encodeURIComponent(token)}`)
      .then(async r => { if (r.status === 404) { setState("gone"); return; } if (!r.ok) throw new Error(); setData(await r.json()); setState("ok"); })
      .catch(() => setState("error"));
  }, [token]);
  return (
    <main className="min-h-screen bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-4xl space-y-4 px-4 py-6 sm:px-6">
        {state === "loading" && <p className="text-sm text-[var(--haip-fg-muted)]">Loading the report…</p>}
        {state === "gone" && <EmptyState title="This link has expired" hint="Report links last 7 days. Open the Analyst page in HAIP for the latest." />}
        {state === "error" && <EmptyState title="Couldn't load the report" hint="Check your connection and refresh." />}
        {state === "ok" && data && (() => {
          const label = `${KIND_LABEL[data.kind]} · ${periodText(data.period)}`;
          return (
            <>
              <header className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{label}</p>
                <h1 className="font-[family-name:var(--font-display)] text-xl font-semibold text-[var(--haip-fg)]">{data.brief.headline}</h1>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill tone="neutral">For {data.viewer.first_name || "you"} · view only</StatusPill>
                  <a className="text-sm font-semibold text-primary underline" href={`${API}/public/analyst/${encodeURIComponent(token)}/report.pdf`}>PDF</a>
                </div>
              </header>
              <HealthChecks checks={data.facts.health} periodLabel={label} />
              <WorkingPanels brief={data.brief} periodLabel={label} />
              {data.brief.recommendations.length > 0 && (
                <Card><CardHeader title="Recommendations" /><CardBody>
                  <ol className="list-decimal space-y-1 pl-5 text-sm text-[var(--haip-fg)]">{data.brief.recommendations.map((r, i) => <li key={i}>{r.action}</li>)}</ol>
                </CardBody></Card>
              )}
              <ReasonsPanels brief={data.brief} />
              <TeamTable facts={data.facts} summary={data.brief.team} periodLabel={label} />
              <DemandMoney brief={data.brief} facts={data.facts} periodLabel={label} />
              <Assign token={token} data={data.assign} />
            </>
          );
        })()}
      </div>
    </main>
  );
}
