"use client";
// Research analyst: competitors, their public numbers (Facebook connection) or posts you paste in, and the brief the
// strategist uses. Numbers are measured or typed by a person; the AI reading is labelled separately.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, openOAuth, studioError, when } from "./types";

interface Competitor { id: string; handle: string; display_name: string | null; followers: number | null; last_snapshot_at: string | null; last_error: string | null }
interface MeasuredComp { handle: string; followers: number | null; followers_source: string | null; median_engagement: number | null; posts_known: number; manual_posts: number; median_engagement_rate: number | null; posts_per_week: number | null; formats: Record<string, number> }
interface Brief { status: string; error: string | null; created_at: string; measured: { competitors: MeasuredComp[] }; assessment: { summary: string; themes: { name: string; why_it_works: string; examples: string[] }[]; formats: string[]; opportunities: string[]; avoid: string[]; not_enough_signal: string[] } | null }
interface Research { competitors: Competitor[]; max_competitors: number; facebook: { status: string; username: string | null; error: string | null; source: string | null; login_available: boolean }; brief: Brief | null }
interface TokenResult { research: boolean; facebook_page: boolean; ig_username: string | null; page_name: string | null; missing: string[] }

const NUM = new Intl.NumberFormat("en-IN");
const pct = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function AddPost({ competitorId, onDone }: { competitorId: string; onDone: () => void }) {
  const { toast } = useToast();
  const [link, setLink] = useState("");
  const [likes, setLikes] = useState("");
  const [comments, setComments] = useState("");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`${STUDIO}/research/competitors/${competitorId}/posts`, {
      permalink: link.trim(), like_count: likes ? Number(likes) : null, comments_count: comments ? Number(comments) : null, note: note || null }),
    onSuccess: () => { setLink(""); setLikes(""); setComments(""); setNote(""); onDone(); },
    onError: e => toast({ variant: "error", title: "Not added", description: studioError(e, "Check the link.") }),
  });
  return (
    <form className="mt-2 grid gap-2 sm:grid-cols-[2fr_6rem_6rem_2fr_auto]" onSubmit={e => { e.preventDefault(); if (link.trim()) add.mutate(); }}>
      <input className={inputCls} placeholder="https://www.instagram.com/p/…" value={link} onChange={e => setLink(e.target.value)} aria-label="Post link" />
      <input className={inputCls} inputMode="numeric" placeholder="Likes" value={likes} onChange={e => setLikes(e.target.value.replace(/\D/g, ""))} aria-label="Likes" />
      <input className={inputCls} inputMode="numeric" placeholder="Comments" value={comments} onChange={e => setComments(e.target.value.replace(/\D/g, ""))} aria-label="Comments" />
      <input className={inputCls} placeholder="What stood out?" maxLength={500} value={note} onChange={e => setNote(e.target.value)} aria-label="Note" />
      <button type="submit" className={btn} disabled={add.isPending || !link.trim()}>Add post</button>
    </form>
  );
}

export function ResearchTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const qc = useQueryClient();
  const { toast } = useToast();
  const [handle, setHandle] = useState("");
  const [followers, setFollowers] = useState("");
  const [openPost, setOpenPost] = useState<string | null>(null);
  const [pasting, setPasting] = useState(false);
  const [sysToken, setSysToken] = useState("");
  const q = useQuery<Research>({ queryKey: ["studio-research"], queryFn: () => api.get(`${STUDIO}/research`).then(r => r.data) });
  const refreshAll = () => qc.invalidateQueries({ queryKey: ["studio-research"] });

  useEffect(() => {     // back from Facebook Login
    const p = new URLSearchParams(window.location.search);
    const fb = p.get("fb");
    if (!fb) return;
    toast(fb === "connected" ? { variant: "success", title: "Facebook connected", description: "Competitor numbers will update on the next refresh." }
                             : { variant: "error", title: "Facebook not connected", description: p.get("reason") ?? "Try again." });
    window.history.replaceState(null, "", window.location.pathname);
  }, [toast]);

  const add = useMutation({
    mutationFn: () => api.post(`${STUDIO}/research/competitors`, { handle, followers: followers ? Number(followers) : null }),
    onSuccess: () => { setHandle(""); setFollowers(""); refreshAll(); },
    onError: e => toast({ variant: "error", title: "Not added", description: studioError(e, "Check the handle.") }),
  });
  const remove = useMutation({ mutationFn: (id: string) => api.delete(`${STUDIO}/research/competitors/${id}`), onSuccess: refreshAll });
  const refresh = useMutation({
    mutationFn: () => api.post(`${STUDIO}/research/refresh`),
    onSuccess: () => { toast({ variant: "success", title: "Research started", description: "The brief updates in a minute." }); setTimeout(refreshAll, 20000); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  const disconnect = useMutation({ mutationFn: () => api.delete(`${STUDIO}/research/facebook`), onSuccess: refreshAll });
  const saveToken = useMutation({   // a Meta System User token: connects Research (and the Facebook Page); WhatsApp and Instagram DMs untouched
    mutationFn: () => api.post<TokenResult>(`${STUDIO}/research/facebook/token`, { access_token: sysToken.trim() }).then(r => r.data),
    onSuccess: r => {
      setSysToken(""); setPasting(false); refreshAll(); qc.invalidateQueries({ queryKey: ["studio-channels"] });
      const parts = [r.research && `Competitor lookups as @${r.ig_username}`, r.facebook_page && `Facebook Page "${r.page_name}" for posting`].filter(Boolean);
      toast({ variant: "success", title: "Connected", description: parts.join(" · ") + (r.missing.length ? `. Still missing: ${r.missing.join(", ")}` : ".") });
    },
    onError: e => toast({ variant: "error", title: "Not connected", description: studioError(e, "Check the token and try again.") }),
  });

  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) return <Card><EmptyState title="Could not load research" hint={studioError(q.error, "Try again.")} /></Card>;
  const d = q.data;
  const fbOn = d.facebook.status === "active";

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-[13px] font-bold">Competitor numbers from Instagram <StatusPill tone={fbOn ? "success" : d.facebook.status === "error" ? "danger" : "neutral"} className="ml-1">{fbOn ? `Connected${d.facebook.username ? ` as @${d.facebook.username}` : ""}` : d.facebook.status === "error" ? "Needs reconnecting" : "Not connected"}</StatusPill></p>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Uses Meta's Business Discovery (public followers, likes, comments; never reach). Needs a Facebook Page linked to your Instagram{d.facebook.source === "system_user" ? ", connected with a System User token" : ""}. Until then, paste posts below.</p>
          {d.facebook.error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{d.facebook.error}</p>}
        </div>
        {(role === "owner" || role === "manager") && (fbOn
          ? role === "owner" && <button type="button" className={btn} onClick={() => { if (confirm("Disconnect Facebook? Competitor numbers that came from it will be deleted.")) disconnect.mutate(); }}>Disconnect</button>
          : <span className="flex flex-wrap gap-2">
              {role === "owner" && <button type="button" className={d.facebook.login_available ? btn : btnPrimary} onClick={() => setPasting(!pasting)}>{pasting ? "Cancel" : "Use a System User token"}</button>}
              {d.facebook.login_available && <button type="button" className={btnPrimary} onClick={() => openOAuth(`${STUDIO}/research/facebook/oauth-start`)}>Connect Facebook</button>}
            </span>)}
        {pasting && !fbOn && (
          <form className="grid w-full gap-2" onSubmit={e => { e.preventDefault(); if (sysToken.trim()) saveToken.mutate(); }}>
            <p className="text-xs text-[var(--haip-fg-2)]">From Meta Business Settings → System users → Generate token, with instagram_basic, instagram_manage_insights and pages_show_list (add pages_manage_posts and pages_read_engagement to post on the Facebook Page). Assign the Page and the Instagram account to the system user first. This does not change your WhatsApp or Instagram DM connection.</p>
            <div className="flex gap-2">
              <input className={inputCls} type="password" autoComplete="off" spellCheck={false} placeholder="EAA…" value={sysToken}
                onChange={e => setSysToken(e.target.value)} aria-label="System User token" />
              <button type="submit" className={btnPrimary} disabled={saveToken.isPending || !sysToken.trim()}>{saveToken.isPending ? "Checking…" : "Connect"}</button>
            </div>
          </form>
        )}
      </Card>

      <Card>
        <CardHeader title="Competitors" description={`Up to ${d.max_competitors}. Add the accounts you compare yourself with.`}
          actions={<button type="button" className={btn} disabled={refresh.isPending || !d.competitors.length} onClick={() => refresh.mutate()}>Refresh research</button>} />
        <CardBody className="space-y-3">
          <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (handle.trim()) add.mutate(); }}>
            <input className={inputCls} placeholder="@handle" value={handle} onChange={e => setHandle(e.target.value)} aria-label="Competitor handle" />
            <input className={inputCls + " w-36"} inputMode="numeric" placeholder="Followers (optional)" value={followers}
              onChange={e => setFollowers(e.target.value.replace(/\D/g, ""))} aria-label="Followers" />
            <button type="submit" className={btnPrimary} disabled={add.isPending || !handle.trim()}>Add</button>
          </form>
          {!d.competitors.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No competitors yet.</p> : (
            <ul className="divide-y divide-[var(--haip-border)]">
              {d.competitors.map(c => (
                <li key={c.id} className="py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold">@{c.handle} {c.followers != null && <span className="text-xs font-normal text-[var(--haip-fg-subtle)]">· {NUM.format(c.followers)} followers · {when(c.last_snapshot_at)}</span>}</span>
                    <span className="flex gap-2">
                      <button type="button" className={btn} onClick={() => setOpenPost(openPost === c.id ? null : c.id)}>{openPost === c.id ? "Close" : "Add a post"}</button>
                      <button type="button" className={btn} onClick={() => remove.mutate(c.id)}>Remove</button>
                    </span>
                  </div>
                  {c.last_error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{c.last_error}</p>}
                  {openPost === c.id && <AddPost competitorId={c.id} onDone={refreshAll} />}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {d.brief && (
        <>
          <Card>
            <CardHeader title="What the numbers say" description={`Measured on ${when(d.brief.created_at)} · public counts from Instagram, or typed in by your team`} />
            <CardBody className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-[var(--haip-fg-subtle)]"><th className="py-1">Account</th><th>Followers</th><th>Engagement / post</th><th className="hidden sm:table-cell">Posts / week</th><th className="hidden md:table-cell">Formats</th></tr></thead>
                <tbody>
                  {d.brief.measured.competitors.map(c => (
                    <tr key={c.handle} className="border-t border-[var(--haip-border)]">
                      <td className="py-2">@{c.handle}{c.manual_posts ? <span className="text-xs text-[var(--haip-fg-subtle)]"> · {c.manual_posts} pasted</span> : null}</td>
                      <td>{c.followers == null ? "—" : NUM.format(c.followers)}{c.followers_source === "manual" && <span className="text-xs text-[var(--haip-fg-subtle)]"> (typed)</span>}</td>
                      <td>{c.median_engagement_rate != null ? pct(c.median_engagement_rate) : c.median_engagement != null ? `${NUM.format(c.median_engagement)} likes+comments` : "—"}</td>
                      <td className="hidden sm:table-cell">{c.posts_per_week ?? "—"}</td>
                      <td className="hidden md:table-cell">{Object.entries(c.formats).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Research brief" description="An AI reading of the numbers above. The strategist uses it for next week's plan." actions={<StatusPill tone="info">AI</StatusPill>} />
            <CardBody className="space-y-3 text-sm">
              {d.brief.status === "failed" && <p className="text-[var(--haip-status-danger-fg)]">{d.brief.error}</p>}
              {d.brief.assessment && (
                <>
                  <p>{d.brief.assessment.summary}</p>
                  {d.brief.assessment.themes.map(t => (
                    <div key={t.name} className="rounded-xl border border-[var(--haip-border)] p-3">
                      <p className="font-semibold">{t.name}</p><p className="text-[var(--haip-fg-2)]">{t.why_it_works}</p>
                      {t.examples.map(x => <a key={x} href={x} target="_blank" rel="noopener noreferrer nofollow" className="mr-3 text-xs text-primary underline">example</a>)}
                    </div>
                  ))}
                  {!!d.brief.assessment.opportunities.length && <p><b>Opportunities:</b> {d.brief.assessment.opportunities.join(" · ")}</p>}
                  {!!d.brief.assessment.avoid.length && <p><b>Avoid:</b> {d.brief.assessment.avoid.join(" · ")}</p>}
                  {!!d.brief.assessment.not_enough_signal.length && <p className="text-[var(--haip-fg-subtle)]">Not enough data yet: {d.brief.assessment.not_enough_signal.join("; ")}</p>}
                </>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}
