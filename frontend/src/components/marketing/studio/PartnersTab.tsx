"use client";
// Agency M7, Partners (GET/POST /marketing/studio/partners/*). Creator barter stays: request -> free dates from the
// calendar -> a person approves -> booked as a free stay -> deliverables with an ASCI label -> bookings it brought.
// OTA listing copy drafts a person pastes into Airbnb / Booking.com / MakeMyTrip. Review -> post lives in Reviews.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError } from "./types";

const P = `${STUDIO}/partners`;

interface Creator { id: string; handle: string; name: string | null; followers: number | null; platform: string; has_contact: boolean }
interface Deliverable { kind: string; due: string | null; url: string | null; label: string | null; delivered_at: string | null }
interface Deal { id: string; creator: Creator; status: string; property_id: string | null; check_in: string | null; check_out: string | null; comp_value_inr: number; deliverables: Deliverable[]; link: string | null; created_by: string | null }
interface Window { property_id: string; property: string; check_in: string; check_out: string; free_nights: number }
interface OtaCopy { id: string; property_id: string; platform: string; status: string; copy: Record<string, string | string[]> | null; checks: { severity: string; message: string; where: string }[]; error: string | null }

const DEAL: Record<string, { label: string; tone: Tone }> = {
  requested: { label: "Waiting for approval", tone: "warning" }, approved: { label: "Approved: book the stay", tone: "info" },
  booked: { label: "Stay booked", tone: "success" }, delivered: { label: "Delivered", tone: "success" }, cancelled: { label: "Cancelled", tone: "neutral" },
};
const PLATFORM: Record<string, string> = { airbnb: "Airbnb", booking: "Booking.com", makemytrip: "MakeMyTrip" };

function useFail() {
  const { toast } = useToast();
  return (title: string) => (e: unknown) => toast({ variant: "error", title, description: studioError(e, "Try again.") });
}

export function PartnersTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const approver = role === "owner" || role === "manager";
  return (
    <div className="space-y-4">
      <Deals approver={approver} me={session?.user?.id} isOwner={role === "owner"} />
      <Creators />
      <OtaCopies />
    </div>
  );
}

function Creators() {
  const qc = useQueryClient();
  const fail = useFail();
  const [handle, setHandle] = useState("");
  const [followers, setFollowers] = useState("");
  const q = useQuery<Creator[]>({ queryKey: ["studio-creators"], queryFn: () => api.get(`${P}/creators`).then(r => r.data) });
  const add = useMutation({
    mutationFn: () => api.post(`${P}/creators`, { handle, followers: followers ? Number(followers) : null }),
    onSuccess: () => { setHandle(""); setFollowers(""); qc.invalidateQueries({ queryKey: ["studio-creators"] }); },
    onError: fail("Not added"),
  });
  return (
    <Card>
      <CardHeader title="Creators" description="Their reach as they report it; HAIP never scrapes profiles." />
      <CardBody className="space-y-3">
        <form className="grid gap-2 sm:grid-cols-[1fr_10rem_auto]" onSubmit={e => { e.preventDefault(); add.mutate(); }}>
          <input className={inputCls} placeholder="@handle" maxLength={31} value={handle} onChange={e => setHandle(e.target.value)} aria-label="Instagram handle" />
          <input className={inputCls} type="number" inputMode="numeric" min={0} placeholder="Followers" value={followers} onChange={e => setFollowers(e.target.value)} aria-label="Followers" />
          <button type="submit" className={btn} disabled={!handle.trim() || add.isPending}>Add creator</button>
        </form>
        {q.isLoading ? <Skeleton className="h-16 w-full" /> : !q.data?.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No creators yet.</p> : (
          <ul className="flex flex-wrap gap-2">
            {q.data.map(c => <li key={c.id}><StatusPill tone="neutral">@{c.handle}{c.followers ? ` · ${c.followers.toLocaleString("en-IN")}` : ""}</StatusPill></li>)}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function NewDeal({ onDone }: { onDone: () => void }) {
  const fail = useFail();
  const creators = useQuery<Creator[]>({ queryKey: ["studio-creators"], queryFn: () => api.get(`${P}/creators`).then(r => r.data) });
  const windows = useQuery<Window[]>({ queryKey: ["studio-free-dates"], queryFn: () => api.get(`${P}/free-dates`).then(r => r.data) });
  const [creatorId, setCreatorId] = useState("");
  const [win, setWin] = useState("");
  const [value, setValue] = useState("");
  const [kinds, setKinds] = useState<string[]>(["reel", "story"]);
  const make = useMutation({
    mutationFn: () => {
      const w = windows.data?.find(x => `${x.property_id}|${x.check_in}` === win);
      return api.post(`${P}/deals`, { creator_id: creatorId, property_id: w?.property_id ?? null, check_in: w?.check_in ?? null,
        check_out: w?.check_out ?? null, comp_value_inr: Number(value) || 0, deliverables: kinds.map(kind => ({ kind })) });
    },
    onSuccess: onDone, onError: fail("Not requested"),
  });
  return (
    <form className="grid gap-3 rounded-xl border border-[var(--haip-border)] p-3 md:grid-cols-2" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
      <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Creator</span>
        <select className={inputCls} value={creatorId} onChange={e => setCreatorId(e.target.value)}>
          <option value="">Choose…</option>{(creators.data ?? []).map(c => <option key={c.id} value={c.id}>@{c.handle}</option>)}
        </select></label>
      <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Free dates (quiet nights, no long weekends)</span>
        <select className={inputCls} value={win} onChange={e => setWin(e.target.value)}>
          <option value="">{windows.isLoading ? "Checking the calendar…" : windows.data?.length ? "Choose…" : "No free runs in the next 60 days"}</option>
          {(windows.data ?? []).map(w => <option key={`${w.property_id}|${w.check_in}`} value={`${w.property_id}|${w.check_in}`}>{w.property}: {w.check_in} to {w.check_out}</option>)}
        </select></label>
      <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">What the stay would cost (₹)</span>
        <input className={inputCls} type="number" inputMode="numeric" min={0} value={value} onChange={e => setValue(e.target.value)} /></label>
      <fieldset className="space-y-1"><legend className="text-[13px] font-semibold text-[var(--haip-fg-2)]">They post</legend>
        <div className="flex flex-wrap gap-3">
          {["reel", "post", "story", "video"].map(k => (
            <label key={k} className="flex min-h-11 items-center gap-1.5 text-sm"><input type="checkbox" className="size-4" checked={kinds.includes(k)}
              onChange={e => setKinds(e.target.checked ? [...kinds, k] : kinds.filter(x => x !== k))} />{k}</label>
          ))}
        </div></fieldset>
      <div className="md:col-span-2"><button type="submit" className={btnPrimary} disabled={!creatorId || make.isPending}>Request the free stay</button></div>
    </form>
  );
}

function DealRow({ d, approver, mine, isOwner }: { d: Deal; approver: boolean; mine: boolean; isOwner: boolean }) {
  const qc = useQueryClient();
  const fail = useFail();
  const [phone, setPhone] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [url, setUrl] = useState("");
  const [caption, setCaption] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio-deals"] });
  const act = useMutation({ mutationFn: ({ a, body }: { a: string; body?: object }) => api.post(`${P}/deals/${d.id}/${a}`, body ?? {}),
    onSuccess: () => { setOpen(null); setUrl(""); setCaption(""); refresh(); }, onError: fail("Not done") });
  const res = useQuery<{ bookings: number; revenue: number; cost_inr: number; return_per_rupee: number | null }>({
    queryKey: ["studio-deal-results", d.id], enabled: approver && ["booked", "delivered"].includes(d.status),
    queryFn: () => api.get(`${P}/deals/${d.id}/results`).then(r => r.data) });
  const s = DEAL[d.status] ?? { label: d.status, tone: "neutral" as Tone };
  return (
    <li className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--haip-fg)]">@{d.creator.handle}<StatusPill tone={s.tone}>{s.label}</StatusPill></p>
      <p className="text-xs text-[var(--haip-fg-subtle)] tabular-nums">{d.check_in ? `${d.check_in} to ${d.check_out}` : "No dates yet"} · stay worth {formatINR(d.comp_value_inr)}</p>
      {d.link && <p className="text-xs text-[var(--haip-fg-2)] [overflow-wrap:anywhere]">Their link: {d.link}</p>}
      <ul className="space-y-1">
        {d.deliverables.map((x, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 text-xs">
            <StatusPill tone={x.delivered_at ? "success" : "neutral"}>{x.kind}{x.label ? ` · ${x.label}` : ""}</StatusPill>
            {x.url ? <a className="text-primary underline [overflow-wrap:anywhere]" href={x.url} target="_blank" rel="noopener noreferrer">View</a>
              : ["booked", "delivered"].includes(d.status) && <button type="button" className="min-h-11 font-semibold text-primary sm:min-h-0" onClick={() => setOpen(i)}>Mark posted</button>}
          </li>
        ))}
      </ul>
      {open !== null && (
        <form className="grid gap-2" onSubmit={e => { e.preventDefault(); act.mutate({ a: "deliver", body: { index: open, url, caption } }); }}>
          <input className={inputCls} placeholder="https:// link to their post" value={url} onChange={e => setUrl(e.target.value)} />
          <textarea className={inputCls} rows={2} placeholder="Paste their caption: it needs a disclosure like #ad, #collab or #gifted (ASCI)" value={caption} onChange={e => setCaption(e.target.value)} />
          <span className="flex gap-2"><button type="submit" className={btnPrimary} disabled={act.isPending}>Save</button><button type="button" className={btn} onClick={() => setOpen(null)}>Cancel</button></span>
        </form>
      )}
      {res.data && <p className="text-xs text-[var(--haip-fg-2)] tabular-nums">Brought {res.data.bookings} bookings, {formatINR(res.data.revenue)}{res.data.return_per_rupee != null ? ` (₹${res.data.return_per_rupee} per ₹1 of stay)` : ""}</p>}
      <div className="flex flex-wrap gap-2">
        {d.status === "requested" && approver && <button type="button" className={btnPrimary} disabled={act.isPending || (mine && !isOwner)}
          title={mine && !isOwner ? "You asked for this stay; someone else approves it." : undefined} onClick={() => act.mutate({ a: "approve" })}>Approve free stay</button>}
        {d.status === "approved" && approver && (
          <span className="flex flex-wrap gap-2">
            {!d.creator.has_contact && <input className={inputCls + " sm:max-w-[14rem]"} inputMode="tel" placeholder="Creator's phone" value={phone} onChange={e => setPhone(e.target.value)} />}
            <button type="button" className={btnPrimary} disabled={act.isPending} onClick={() => act.mutate({ a: "book", body: phone ? { phone } : {} })}>Book the stay</button>
          </span>
        )}
        {["requested", "approved"].includes(d.status) && <button type="button" className={btn} disabled={act.isPending} onClick={() => act.mutate({ a: "cancel" })}>Cancel</button>}
      </div>
    </li>
  );
}

function Deals({ approver, me, isOwner }: { approver: boolean; me?: string; isOwner: boolean }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const q = useQuery<Deal[]>({ queryKey: ["studio-deals"], queryFn: () => api.get(`${P}/deals`).then(r => r.data) });
  return (
    <Card>
      <CardHeader title="Creator stays" description="A free stay on quiet nights for posts with a clear #ad / #collab label; bookings from their link are counted." />
      <CardBody className="space-y-3">
        {adding ? <NewDeal onDone={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["studio-deals"] }); }} />
          : <button type="button" className={btn} onClick={() => setAdding(true)}>Request a creator stay</button>}
        {q.isLoading ? <Skeleton className="h-24 w-full" /> : q.isError ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load.")}</p>
          : !q.data?.length ? <EmptyState title="No creator stays yet" hint="Add a creator below, then request a stay." /> : (
            <ul className="space-y-3">{q.data.map(d => <DealRow key={d.id} d={d} approver={approver} mine={d.created_by === me} isOwner={isOwner} />)}</ul>
          )}
      </CardBody>
    </Card>
  );
}

function OtaCopies() {
  const qc = useQueryClient();
  const fail = useFail();
  const { toast } = useToast();
  const props = useQuery<{ id: string; name: string }[]>({ queryKey: ["properties"], queryFn: () => api.get("/properties").then(r => r.data) });
  const [prop, setProp] = useState("");
  const [platform, setPlatform] = useState("airbnb");
  const q = useQuery<OtaCopy[]>({ queryKey: ["studio-ota"], queryFn: () => api.get(`${P}/ota`).then(r => r.data),
    refetchInterval: d => (d.state.data?.some(c => c.status === "pending") ? 4000 : false) });
  const make = useMutation({ mutationFn: () => api.post(`${P}/ota`, { property_id: prop, platform }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-ota"] }), onError: fail("Not started") });
  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => toast({ variant: "success", title: "Copied" }));
  const list = Array.isArray(props.data) ? props.data : [];
  return (
    <Card>
      <CardHeader title="Listing copy for OTAs" description="Drafted from your own property facts; you paste it into the OTA." />
      <CardBody className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-[1fr_12rem_auto]">
          <select className={inputCls} aria-label="Property" value={prop} onChange={e => setProp(e.target.value)}>
            <option value="">Choose a property…</option>{list.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className={inputCls} aria-label="Platform" value={platform} onChange={e => setPlatform(e.target.value)}>
            {Object.entries(PLATFORM).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button type="button" className={btnPrimary} disabled={!prop || make.isPending} onClick={() => make.mutate()}>Draft copy</button>
        </div>
        {(q.data ?? []).slice(0, 3).map(c => (
          <div key={c.id} className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
            <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">{PLATFORM[c.platform]} · {list.find(p => p.id === c.property_id)?.name ?? "Property"}
              <StatusPill tone={c.status === "ready" ? "success" : c.status === "failed" ? "danger" : "info"}>{c.status === "pending" ? "Writing…" : c.status}</StatusPill></p>
            {c.error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{c.error}</p>}
            {c.copy && Object.entries(c.copy).map(([k, v]) => {
              const text = Array.isArray(v) ? v.join("\n") : v;
              return text ? (
                <div key={k} className="space-y-1">
                  <p className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{k.replace(/_/g, " ")}
                    <button type="button" className="min-h-11 px-2 normal-case text-primary sm:min-h-0" onClick={() => copy(text)}>Copy</button></p>
                  <p className="whitespace-pre-line text-sm text-[var(--haip-fg-2)]">{text}</p>
                </div>
              ) : null;
            })}
            {c.checks.length > 0 && <ul className="space-y-1">{c.checks.map((f, i) => <li key={i} className="text-xs text-[var(--haip-status-warning-fg)]">{f.where}: {f.message}</li>)}</ul>}
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

/** Reviews tab: a 5-star review becomes a draft post, once, after the person records how the guest agreed. */
export function ReviewToPost({ reviewId, contentId }: { reviewId: string; contentId: string | null }) {
  const qc = useQueryClient();
  const fail = useFail();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const make = useMutation({ mutationFn: () => api.post(`${P}/reviews/${reviewId}/to-post`, { consent_note: note }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["studio-guest-reviews"] }); toast({ variant: "success", title: "Draft post made", description: "Find it in Content; approve it, then promote it as an ad." }); },
    onError: fail("Not made") });
  if (contentId) return <StatusPill tone="success">Made into a post</StatusPill>;
  if (!open) return <button type="button" className={btn} onClick={() => setOpen(true)}>Make a post from it</button>;
  return (
    <form className="grid gap-2" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
      <input className={inputCls} maxLength={300} placeholder="How did the guest agree? e.g. “said yes on WhatsApp, 20 Oct”" value={note} onChange={e => setNote(e.target.value)} />
      <span className="flex gap-2"><button type="submit" className={btnPrimary} disabled={note.trim().length < 5 || make.isPending}>Make the post</button>
        <button type="button" className={btn} onClick={() => setOpen(false)}>Cancel</button></span>
    </form>
  );
}
