"use client";
// Agency M3: the extra publishing channels (Facebook Page, Google Business Profile) and Google review replies.
// Backend: endpoints/marketing_channels.py. Connecting is owner/manager; choosing a Page/location is owner.
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";
import { WhatsAppDefaults } from "./OutreachPanels";
import { ReviewToPost } from "./PartnersTab";

interface Channels {
  facebook: { available: boolean; connected: boolean; page_name: string | null; pages: { id: string; name: string | null }[] };
  google: { available: boolean; connected: boolean; location_title: string | null; locations: { location: string; title: string | null }[] };
}

function oauthUrl(provider: "facebook" | "google", token: string | null): string | null {
  if (!token) return null;
  const raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
  const base = raw.endsWith("/api/v1") ? raw : `${raw}/api/v1`;
  return `${base}/marketing/studio/channels/${provider}/oauth-start?token=${encodeURIComponent(token)}`;
}

export function ChannelsPanel() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwner = role === "owner";
  const canConnect = role === "owner" || role === "manager";
  const token = (session as unknown as { accessToken?: string })?.accessToken ?? null;
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Channels>({ queryKey: ["studio-channels"], queryFn: () => api.get(`${STUDIO}/channels`).then(r => r.data) });
  const choose = useMutation({
    mutationFn: ({ path, body }: { path: string; body: object }) => api.put(`${STUDIO}/channels/${path}`, body),
    onSuccess: r => qc.setQueryData(["studio-channels"], r.data),
    onError: e => toast({ variant: "error", title: "Not changed", description: studioError(e, "Try again.") }),
  });
  const c = q.data;
  if (!c) return null;
  const row = (name: string, available: boolean, connected: boolean, provider: "facebook" | "google", detail: ReactNode, needs: string) => (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <p className="text-sm font-semibold">{name} {connected && <StatusPill tone="success" className="ml-1">Connected</StatusPill>}</p>
        <div className="text-xs text-[var(--haip-fg-subtle)]">{!available ? "Not set up on this HAIP server yet." : connected ? detail : needs}</div>
      </div>
      {available && !connected && canConnect && oauthUrl(provider, token) && <a className={btnPrimary} href={oauthUrl(provider, token) as string}>Connect</a>}
    </div>
  );
  return (
    <Card>
      <CardHeader title="Channels" description="Approved posts can also go to your Facebook Page and Google Business Profile, from the same approval." />
      <CardBody className="space-y-4">
        {row("Facebook Page", c.facebook.available, c.facebook.connected, "facebook",
          c.facebook.pages.length > 1 && isOwner ? (
            <select className={inputCls + " mt-1"} aria-label="Facebook Page" value={c.facebook.pages.find(p => p.name === c.facebook.page_name)?.id}
              onChange={e => choose.mutate({ path: "facebook/page", body: { page_id: e.target.value } })}>
              {c.facebook.pages.map(p => <option key={p.id} value={p.id}>{p.name ?? p.id}</option>)}
            </select>) : <>Posts go to {c.facebook.page_name}.</>,
          "Needs a Facebook Page you manage; Meta must approve HAIP for page posting.")}
        <div className="border-t border-[var(--haip-border)]" />
        {row("Google Business Profile", c.google.available, c.google.connected, "google",
          c.google.locations.length > 1 && isOwner ? (
            <select className={inputCls + " mt-1"} aria-label="Google location" value={c.google.locations.find(l => l.title === c.google.location_title)?.location}
              onChange={e => choose.mutate({ path: "google/location", body: { location: e.target.value } })}>
              {c.google.locations.map(l => <option key={l.location} value={l.location}>{l.title ?? l.location}</option>)}
            </select>) : <>Posts and review replies for {c.google.location_title}.</>,
          "Needs the Google account that manages your Business Profile.")}
        {isOwner && <>
          <div className="border-t border-[var(--haip-border)]" />
          <div className="space-y-2">
            <p className="text-sm font-semibold">WhatsApp campaign drafts</p>
            <WhatsAppDefaults />
          </div>
        </>}
      </CardBody>
    </Card>
  );
}

interface Review {
  id: string; rating: number | null; reviewer: string | null; comment: string | null; reviewed_at: string | null;
  reply_status: "none" | "drafting" | "draft" | "approved" | "posted" | "failed"; reply_draft: string | null;
  reply_origin: "ai" | "human" | null; reply_posted: string | null; reply_error: string | null; drafted_by: string | null;
  content_id?: string | null;
}

const REPLY_TONE: Record<Review["reply_status"], Tone> = { none: "warning", drafting: "info", draft: "info", approved: "info", posted: "success", failed: "danger" };
const REPLY_LABEL: Record<Review["reply_status"], string> = { none: "No reply", drafting: "Writing…", draft: "Draft ready", approved: "Approved", posted: "Replied", failed: "Needs attention" };

function ReviewRow({ r, canPost, isOwner, me }: { r: Review; canPost: boolean; isOwner: boolean; me?: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [text, setText] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio-guest-reviews"] });
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: studioError(e, "Try again.") });
  const ai = useMutation({ mutationFn: () => api.post(`${STUDIO}/guest-reviews/${r.id}/draft`), onSuccess: refresh, onError: fail("Not started") });
  const save = useMutation({ mutationFn: () => api.put(`${STUDIO}/guest-reviews/${r.id}/draft`, { text }), onSuccess: () => { setText(null); refresh(); }, onError: fail("Not saved") });
  const post = useMutation({ mutationFn: () => api.post(`${STUDIO}/guest-reviews/${r.id}/post`),
    onSuccess: res => { refresh(); toast(res.data.reply_status === "posted" ? { variant: "success", title: "Reply posted on Google" } : { variant: "error", title: "Not posted", description: res.data.reply_error }); },
    onError: fail("Not posted") });
  const ownDraft = r.reply_origin === "human" && r.drafted_by === me;
  return (
    <li className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">{"★".repeat(r.rating ?? 0)}<span className="text-[var(--haip-fg-subtle)]">{"★".repeat(5 - (r.rating ?? 0))}</span></span>
        <span>{r.reviewer ?? "A guest"}</span><span className="text-xs text-[var(--haip-fg-subtle)]">{when(r.reviewed_at)}</span>
        <StatusPill tone={REPLY_TONE[r.reply_status]}>{REPLY_LABEL[r.reply_status]}</StatusPill>
      </p>
      {r.comment && <p className="text-sm text-[var(--haip-fg-2)]">{r.comment}</p>}
      {canPost && r.rating === 5 && r.comment && <ReviewToPost reviewId={r.id} contentId={r.content_id ?? null} />}
      {r.reply_status === "posted" ? <p className="rounded-lg bg-[var(--haip-surface)] p-2 text-sm">{r.reply_posted}</p> : (
        <div className="space-y-2">
          {r.reply_error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{r.reply_error}</p>}
          <textarea className={inputCls} rows={3} maxLength={1000} placeholder="Write a reply, or ask the AI for a draft"
            value={text ?? r.reply_draft ?? ""} onChange={e => setText(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btn} disabled={ai.isPending || r.reply_status === "drafting"} onClick={() => ai.mutate()}>{r.reply_draft ? "Ask the AI again" : "Draft with AI"}</button>
            {text !== null && text !== (r.reply_draft ?? "") && <button type="button" className={btn} disabled={save.isPending || text.trim().length < 2} onClick={() => save.mutate()}>Save draft</button>}
            {canPost && r.reply_draft && text === null && (
              <button type="button" className={btnPrimary} disabled={post.isPending || (ownDraft && !isOwner)} onClick={() => post.mutate()}
                title={ownDraft ? "You wrote this reply; someone else posts it unless you are the owner." : undefined}>Post reply on Google</button>)}
          </div>
        </div>
      )}
    </li>
  );
}

export function ReviewsTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canPost = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ reviews: Review[]; waiting: number }>({ queryKey: ["studio-guest-reviews"],
    queryFn: () => api.get(`${STUDIO}/guest-reviews`).then(r => r.data),
    refetchInterval: d => (d.state.data?.reviews.some(r => r.reply_status === "drafting") ? 4000 : false) });
  const sync = useMutation({ mutationFn: () => api.post(`${STUDIO}/guest-reviews/sync`),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ["studio-guest-reviews"] }); toast({ variant: "success", title: `${r.data.new} new review${r.data.new === 1 ? "" : "s"}` }); },
    onError: e => toast({ variant: "error", title: "Could not fetch reviews", description: studioError(e, "Connect Google Business Profile in Library › Channels.") }) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--haip-fg-muted)]">Google reviews of your Business Profile. Replies are drafted here and posted only when someone presses Post.</p>
        <button type="button" className={btn} disabled={sync.isPending} onClick={() => sync.mutate()}>Fetch new reviews</button>
      </div>
      {q.isLoading ? <Skeleton className="h-40 w-full" /> : q.isError ? (
        <Card><EmptyState title="Could not load reviews" hint={studioError(q.error, "Try again.")} /></Card>
      ) : !q.data?.reviews.length ? (
        <Card><EmptyState title="No reviews yet" hint="Connect Google Business Profile in Library › Channels, then fetch reviews." /></Card>
      ) : (
        <ul className="space-y-3">{q.data.reviews.map(r => <ReviewRow key={r.id} r={r} canPost={canPost} isOwner={role === "owner"} me={session?.user?.id} />)}</ul>
      )}
    </div>
  );
}
