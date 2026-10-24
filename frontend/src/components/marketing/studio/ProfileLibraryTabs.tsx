"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, type Asset } from "./types";
import { AiImagesPanel } from "./AiImagesPanel";
import { BrandDraftPanel, ClaimsEditor, PhotoTagsRow, TaggingBar, type Claim } from "./BrainPanels";
import { CreativePanel } from "./CreativePanel";
import { ChannelsPanel } from "./ChannelsReviews";
import { useSession } from "next-auth/react";

interface VoiceTrait { trait: string; we_are: string; we_are_not: string; sounds_like: string | null; not_like: string | null }
type Channel = "instagram" | "whatsapp" | "review_replies" | "ads";
interface Profile {
  tagline: string | null; description: string | null; audience: string | null; tone: string | null;
  usps: string[]; avoid: string[]; city: string | null; region: string | null; default_hashtags: string[];
  voice?: VoiceTrait[]; channel_tone?: Partial<Record<Channel, string | null>>; claims?: Claim[]; home_state?: string | null;
  [k: string]: unknown;
}

const CHANNELS: { key: Channel; label: string; hint: string }[] = [
  { key: "instagram", label: "Instagram", hint: "e.g. unhurried and visual; short paragraphs" },
  { key: "whatsapp", label: "WhatsApp", hint: "e.g. personal, first names, no hashtags" },
  { key: "review_replies", label: "Review replies", hint: "e.g. thank by name, own any problem, no excuses" },
  { key: "ads", label: "Ads", hint: "e.g. one clear offer, plain words" },
];
const BLANK_TRAIT: VoiceTrait = { trait: "", we_are: "", we_are_not: "", sounds_like: null, not_like: null };

/** Brand voice the way an agency style guide writes it: each trait says what you are and where it stops. */
function VoiceEditor({ value, onChange }: { value: VoiceTrait[]; onChange: (v: VoiceTrait[]) => void }) {
  const set = (i: number, patch: Partial<VoiceTrait>) => onChange(value.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const field = (i: number, key: keyof VoiceTrait, label: string, max: number, placeholder: string) => (
    <label className="space-y-1">
      <span className="text-xs font-semibold text-[var(--haip-fg-2)]">{label}</span>
      <input className={inputCls} maxLength={max} placeholder={placeholder} value={value[i][key] ?? ""}
        onChange={e => set(i, { [key]: e.target.value || (key === "sounds_like" || key === "not_like" ? null : "") })} />
    </label>
  );
  return (
    <div className="space-y-3">
      {value.map((t, i) => (
        <fieldset key={i} className="grid gap-3 rounded-xl border border-[var(--haip-border)] p-3 sm:grid-cols-2">
          <legend className="sr-only">Voice trait {i + 1}</legend>
          <div className="flex items-end gap-2 sm:col-span-2">
            <div className="flex-1">{field(i, "trait", "Trait", 40, "e.g. Warm")}</div>
            <button type="button" className={btn} onClick={() => onChange(value.filter((_, j) => j !== i))}>Remove</button>
          </div>
          {field(i, "we_are", "We are", 200, "Warm and specific: we name the place and the hour")}
          {field(i, "we_are_not", "We are not", 200, "Gushing: no \"magical\", no exclamation marks")}
          {field(i, "sounds_like", "Sounds like", 200, "\"Chai on the step at 7, mist still on the estate.\"")}
          {field(i, "not_like", "Doesn't sound like", 200, "\"An unforgettable, magical experience awaits!\"")}
        </fieldset>
      ))}
      {value.length < 5 && (
        <button type="button" className={btn} onClick={() => onChange([...value, { ...BLANK_TRAIT }])}>Add a voice trait</button>
      )}
    </div>
  );
}

const TEXT: { key: keyof Profile; label: string; max: number; rows?: number; hint?: string }[] = [
  { key: "tagline", label: "Tagline", max: 160 },
  { key: "description", label: "What you offer", max: 2000, rows: 4 },
  { key: "audience", label: "Who your guests are", max: 600, rows: 2 },
  { key: "tone", label: "How you sound", max: 300, hint: "e.g. warm, understated, never salesy" },
  { key: "city", label: "City", max: 80 },
  { key: "region", label: "Region", max: 80 },
  { key: "home_state", label: "State (for holidays)", max: 40, hint: "e.g. Karnataka" },
];
const LISTS: { key: "usps" | "avoid" | "default_hashtags"; label: string; hint: string }[] = [
  { key: "usps", label: "What makes you different", hint: "One per line." },
  { key: "avoid", label: "Words and claims never to use", hint: "One per line. Content using them is refused." },
  { key: "default_hashtags", label: "Your usual hashtags", hint: "Separate with spaces." },
];

export function ProfileTab() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ brand_name: string; profile: Profile }>({ queryKey: ["studio-profile"], queryFn: () => api.get(`${STUDIO}/profile`).then(r => r.data) });
  const [p, setP] = useState<Profile | null>(null);
  const [lists, setLists] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!q.data) return;
    setP(q.data.profile);
    setLists({ usps: q.data.profile.usps.join("\n"), avoid: q.data.profile.avoid.join("\n"), default_hashtags: q.data.profile.default_hashtags.join(" ") });
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put(`${STUDIO}/profile`, {
      ...p,
      usps: lists.usps.split("\n").map(s => s.trim()).filter(Boolean),
      avoid: lists.avoid.split("\n").map(s => s.trim()).filter(Boolean),
      default_hashtags: lists.default_hashtags.split(/\s+/).filter(Boolean),
      voice: (p?.voice ?? []).filter(t => t.trait.trim() && t.we_are.trim() && t.we_are_not.trim()),   // half-written traits are dropped
      claims: (p?.claims ?? []).filter(c => c.text.trim().length >= 3),
    }),
    onSuccess: r => { qc.setQueryData(["studio-profile"], r.data); toast({ variant: "success", title: "Profile saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Check the fields.") }),
  });
  if (q.isLoading || !p) return q.isError ? <Card><EmptyState title="Could not load the profile" hint={studioError(q.error, "Try again.")} /></Card> : <Skeleton className="h-64 w-full" />;

  return (
    <Card>
      <CardHeader title={q.data?.brand_name ?? "Business profile"} description="What the AI may say about you. It never invents anything beyond this and your property details." />
      <CardBody>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
          <div className="md:col-span-2">
            <BrandDraftPanel onApply={d => {
              setP({ ...p, tagline: d.tagline || p.tagline, audience: d.audience || p.audience, tone: d.tone || p.tone,
                voice: d.voice.length ? d.voice : p.voice, channel_tone: { ...(p.channel_tone ?? {}), ...Object.fromEntries(Object.entries(d.channel_tone).filter(([, v]) => v)) },
                claims: [...(p.claims ?? []), ...d.claims.filter(c => !(p.claims ?? []).some(x => x.text === c.text))] });
              if (d.usps.length) setLists({ ...lists, usps: d.usps.join("\n") });
              toast({ title: "Draft added to the form", description: "Check it, then press Save profile." });
            }} />
          </div>
          {TEXT.map(f => (
            <label key={f.key} className={f.rows ? "space-y-1 md:col-span-2" : "space-y-1"}>
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{f.label}</span>
              {f.rows ? (
                <textarea className={inputCls} rows={f.rows} maxLength={f.max} value={(p[f.key] as string) ?? ""} onChange={e => setP({ ...p, [f.key]: e.target.value || null })} />
              ) : (
                <input className={inputCls} maxLength={f.max} value={(p[f.key] as string) ?? ""} onChange={e => setP({ ...p, [f.key]: e.target.value || null })} />
              )}
              {f.hint && <span className="block text-xs text-[var(--haip-fg-subtle)]">{f.hint}</span>}
            </label>
          ))}
          {LISTS.map(f => (
            <label key={f.key} className="space-y-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{f.label}</span>
              <textarea className={inputCls} rows={3} value={lists[f.key] ?? ""} onChange={e => setLists({ ...lists, [f.key]: e.target.value })} />
              <span className="block text-xs text-[var(--haip-fg-subtle)]">{f.hint}</span>
            </label>
          ))}
          <section className="space-y-2 md:col-span-2">
            <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Brand voice</h3>
            <p className="text-xs text-[var(--haip-fg-subtle)]">Up to five traits. The copywriter follows them and the brand review checks every draft against them.</p>
            <VoiceEditor value={p.voice ?? []} onChange={voice => setP({ ...p, voice })} />
          </section>
          <section className="space-y-2 md:col-span-2">
            <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Facts you approve for posts</h3>
            <p className="text-xs text-[var(--haip-fg-subtle)]">Distances, awards, what is included. The copywriter may use these as written; anything else with a number is flagged.</p>
            <ClaimsEditor value={p.claims ?? []} onChange={claims => setP({ ...p, claims })} />
          </section>
          <section className="space-y-2 md:col-span-2">
            <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Tone by channel</h3>
            <p className="text-xs text-[var(--haip-fg-subtle)]">The voice stays the same everywhere; the tone shifts by where people read it.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {CHANNELS.map(c => (
                <label key={c.key} className="space-y-1">
                  <span className="text-xs font-semibold text-[var(--haip-fg-2)]">{c.label}</span>
                  <input className={inputCls} maxLength={200} placeholder={c.hint} value={p.channel_tone?.[c.key] ?? ""}
                    onChange={e => setP({ ...p, channel_tone: { ...(p.channel_tone ?? {}), [c.key]: e.target.value || null } })} />
                </label>
              ))}
            </div>
          </section>
          <div className="md:col-span-2"><button type="submit" className={btnPrimary} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save profile"}</button></div>
        </form>
      </CardBody>
    </Card>
  );
}

// The server's own reason when it gave one; otherwise the HTTP status in plain words (a proxy size limit answers 413 with no JSON).
export function uploadError(e: unknown): string {
  const status = (e as { response?: { status?: number } })?.response?.status;
  const plain = status === 413 ? "too big for the server's upload limit"
    : status ? `server answered ${status}`
    : "the upload didn't reach the server (connection dropped or file too big)";
  return studioError(e, `${plain}. Photos: JPEG, PNG or WebP up to 10 MB. Clips: MP4 or MOV, up to 90 s and 100 MB.`);
}

export function LibraryTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canReview = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [render, setRender] = useState<Asset | null>(null);
  const [headline, setHeadline] = useState("");
  const [subline, setSubline] = useState("");
  const [template, setTemplate] = useState("portrait_panel");
  const assets = useQuery<Asset[]>({ queryKey: ["studio-media"], queryFn: () => api.get(`${STUDIO}/media`).then(r => r.data) });
  const templates = useQuery<{ key: string; label: string }[]>({ queryKey: ["studio-templates"], queryFn: () => api.get(`${STUDIO}/templates`).then(r => r.data) });
  const upload = useMutation({
    // One file at a time, so one bad file never stops the rest. A video goes to /media/clips (agency M3).
    mutationFn: async (files: File[]) => {
      const failed: string[] = [];
      for (const f of files) {
        const fd = new FormData(); fd.append("file", f);
        try { await api.post(`${STUDIO}/media${f.type.startsWith("video/") ? "/clips" : ""}`, fd); }
        catch (e) { failed.push(`${f.name}: ${uploadError(e)}`); }
      }
      return { done: files.length - failed.length, failed };
    },
    onSuccess: ({ done, failed }) => {
      qc.invalidateQueries({ queryKey: ["studio-media"] });
      if (failed.length) toast({ variant: "error", title: `${done} uploaded, ${failed.length} failed`, description: failed.join(" · ") });
      else toast({ variant: "success", title: done === 1 ? "Uploaded" : `${done} files uploaded` });
    },
  });
  const review = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.post(`${STUDIO}/media/${id}/${approve ? "approve" : "reject"}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-media"] }),
    onError: e => toast({ variant: "error", title: "Not done", description: studioError(e, "Try again.") }),
  });
  const make = useMutation({
    mutationFn: () => api.post(`${STUDIO}/media/${render?.id}/render`, { template, headline, subline: subline || null }),
    onSuccess: () => { setRender(null); setHeadline(""); setSubline(""); qc.invalidateQueries({ queryKey: ["studio-media"] }); toast({ variant: "success", title: "Creative added to the library" }); },
    onError: e => toast({ variant: "error", title: "Not made", description: studioError(e, "Try again.") }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--haip-fg-muted)]">Your own photos, creatives made from them, and approved AI images.</p>
        <input ref={file} type="file" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime" className="sr-only"
          onChange={e => { const fs = Array.from(e.target.files ?? []); if (fs.length) upload.mutate(fs); e.target.value = ""; }} />
        <button type="button" className={btnPrimary} disabled={upload.isPending} onClick={() => file.current?.click()}>{upload.isPending ? "Uploading…" : "Upload photos or clips"}</button>
      </div>
      <TaggingBar />
      <ChannelsPanel />
      <CreativePanel photos={assets.data ?? []} />
      <AiImagesPanel />
      {render && (
        <Card className="p-4">
          <form className="grid gap-3 sm:grid-cols-[auto_1fr_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Shape</span>
              <select className={inputCls} value={template} onChange={e => setTemplate(e.target.value)}>
                {(templates.data ?? []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Headline</span>
              <input className={inputCls} maxLength={80} value={headline} onChange={e => setHeadline(e.target.value)} /></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold">Second line</span>
              <input className={inputCls} maxLength={120} value={subline} onChange={e => setSubline(e.target.value)} /></label>
            <span className="flex gap-2">
              <button type="submit" className={btnPrimary} disabled={!headline.trim() || make.isPending}>Make creative</button>
              <button type="button" className={btn} onClick={() => setRender(null)}>Cancel</button>
            </span>
          </form>
        </Card>
      )}
      {assets.isLoading ? <Skeleton className="h-40 w-full" /> : assets.isError ? (
        <Card><EmptyState title="Could not load the library" hint={studioError(assets.error, "Try again.")} /></Card>
      ) : !assets.data?.length ? (
        <Card><EmptyState title="No photos yet" hint="Upload property photos to build posts and creatives from." /></Card>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {assets.data.map(a => (
            <li key={a.id} className="overflow-hidden rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)]">
              {a.url && a.mime_type.startsWith("video/") ? <video src={a.url} className="aspect-square w-full object-cover" muted playsInline controls preload="metadata" />
                : a.url ? <img src={a.url} alt={a.alt_text ?? ""} className="aspect-square w-full object-cover" loading="lazy" /> : <div className="aspect-square bg-[var(--haip-surface)]" />}
              <div className="flex flex-wrap items-center justify-between gap-2 p-2">
                {a.source === "ai" ? (
                  <StatusPill tone={a.status === "pending_review" ? "warning" : "info"}>{a.mime_type.startsWith("video/") ? (a.status === "pending_review" ? "AI video · needs approval" : "AI video")
                    : a.status === "pending_review" ? "AI image · needs approval" : "AI image"}</StatusPill>
                ) : <StatusPill tone={a.source === "template" || a.source === "canva" ? "brand" : "neutral"}>{a.source === "template" ? "Creative" : a.source === "canva" ? "Canva design"
                  : a.mime_type.startsWith("video/") ? `Clip${a.duration_ms ? ` · ${Math.round(a.duration_ms / 1000)} s` : ""}` : "Photo"}</StatusPill>}
                {a.status !== "pending_review" && (a.source === "upload" || a.source === "ai") && a.mime_type.startsWith("image/") && (
                  <button type="button" className="min-h-11 px-1 text-xs font-semibold text-primary sm:min-h-0" onClick={() => setRender(a)}>Make creative</button>
                )}
              </div>
              <PhotoTagsRow a={a} canApprove={canReview} />
              {a.status === "pending_review" && canReview && (
                <div className="flex gap-2 px-2 pb-2">
                  <button type="button" className={btnPrimary + " flex-1"} disabled={review.isPending || (role !== "owner" && a.created_by === session?.user?.id)}
                    title={role !== "owner" && a.created_by === session?.user?.id ? "You asked for this image, so someone else must approve it." : undefined}
                    onClick={() => review.mutate({ id: a.id, approve: true })}>Approve</button>
                  <button type="button" className={btn + " flex-1"} disabled={review.isPending} onClick={() => review.mutate({ id: a.id, approve: false })}>Reject</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
