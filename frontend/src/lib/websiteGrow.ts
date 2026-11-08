// Website > Grow and the website SEO agency (backend endpoints/website_seo_agency.py, services/website_seo_agency.py).
// Shapes are hand-written next to their use. growRow is pure (tested): what one task row says and where it goes.
import api from "@/lib/api";

export type Level = "off" | "suggest" | "autopilot";
export const LEVELS: Level[] = ["off", "suggest", "autopilot"];
export const LEVEL_WORDS: Record<Level, string> = { off: "Off", suggest: "Asks first", autopilot: "On its own" };
export const GROW_MANAGE_ROLES = ["owner", "manager"];

export type Role = { role: string; label: string; does: string; level: Level; max_level: Level; effective_level: Level };
export type ScorePart = { key: "setup" | "technical" | "found" | "search"; label: string; points: number; max: number; why: string };
export type GrowTask =
  | { kind: "sop_step"; role: string; instance_id: string; checklist: string; title: string; due_at: string; overdue: boolean }
  | { kind: "start_checklist"; role: string; template_key: string; title: string; property_name: string | null }
  | { kind: "guide_draft"; role: string; id: string; title: string; status: string }
  | { kind: "review_replies"; role: string; count: number }
  | { kind: "fixes"; role: string; alt: number; titles: number }
  | { kind: "outreach"; role: string; creator_id: string; handle: string; platform: string; text: string; ai: boolean }
  | { kind: "ads"; role: string; campaign: string; action: "pause" | "raise"; why?: string; effect_inr?: number };
export type Grow = {
  settings: { paused: boolean; roles: Record<string, Level> };
  roster: Role[];
  last_run: { id: string; at: string | null; trigger: string; roles: Record<string, string> | null } | null;
  score: { total: number; parts: ScorePart[] };
  brief: { text: string | null; actions: string[] } | null;
  checker: { problems?: { key: string; title: string; detail: string }[] | null; slow_pages?: { page: string; verdict: string }[] | null;
    sitemap?: { ok: boolean; detail: string } | null; applied?: { alt: number; titles: number } | null } | null;
  tasks: GrowTask[];
  results: { days: number; money_restricted: boolean; google: { times_shown: number | null; change_pct: number | null };
    website: { visits: number; enquiries: number; bookings: number; value?: number } | null;
    ads: { spend?: number; bookings?: number; revenue?: number; roas?: number | null } | null };
};

const WEB = "/websites";
export const growApi = {
  get: () => api.get<Grow>(`${WEB}/grow`).then(r => r.data),
  setAgency: (body: { roles?: Record<string, Level>; paused?: boolean }) => api.put(`${WEB}/seo-agency`, body).then(r => r.data),
  run: () => api.post(`${WEB}/seo-agency/run`).then(r => r.data),
  applyFixes: () => api.post<{ alt: number; titles: number }>(`${WEB}/seo-agency/fixes/apply`).then(r => r.data),
};

export const inr = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN");

export type RowTone = "danger" | "warning" | "brand" | "neutral";
export type GrowRow = { key: string; title: string; subtitle: string; tag: string; tone: RowTone; href?: string;
  copy?: string; apply?: boolean };

function dueWord(iso: string, overdue: boolean): string {
  if (overdue) return "Late";
  return new Date(iso).toLocaleDateString("en-IN", { weekday: "short", timeZone: "Asia/Kolkata" });
}

export function growRow(t: GrowTask, i: number): GrowRow {
  switch (t.kind) {
    case "sop_step":
      return { key: `s${t.instance_id}${t.title}`, title: t.title, subtitle: `${t.checklist} · you do it`, tag: dueWord(t.due_at, t.overdue),
        tone: t.overdue ? "danger" : "brand", href: `/dashboard/marketing/sops/${t.instance_id}` };
    case "start_checklist":
      return { key: `c${t.template_key}${i}`, title: `Start: ${t.title}`, subtitle: t.property_name ? `${t.property_name} · checklist` : "Checklist",
        tag: "Start", tone: "neutral", href: "/dashboard/marketing/sops" };
    case "guide_draft":
      return { key: `g${t.id}`, title: `Guide: ${t.title}`, subtitle: t.status === "in_review" ? "Content writer · waiting for approval"
        : "Content writer · read it, then send for approval", tag: "Approve", tone: "warning", href: "/dashboard/marketing/website" };
    case "review_replies":
      return { key: "reviews", title: `${t.count} review ${t.count === 1 ? "reply" : "replies"} drafted`, subtitle: "Google reviews · you post them",
        tag: "Approve", tone: "warning", href: "/dashboard/marketing/studio?tab=reviews" };
    case "fixes":
      return { key: "fixes", title: "Fix photo descriptions and page titles", subtitle: [t.alt && `${t.alt} photo${t.alt === 1 ? "" : "s"}`,
        t.titles && `${t.titles} title${t.titles === 1 ? "" : "s"}`].filter(Boolean).join(", ") + " · titles go to your draft", tag: "Fix",
        tone: "brand", apply: true };
    case "outreach":
      return { key: `o${t.creator_id}`, title: `Ask @${t.handle.replace(/^@/, "")} for a link`, subtitle: `Links and citations · ${t.platform}`,
        tag: "Send", tone: "brand", copy: t.text };
    case "ads":
      return { key: `a${t.campaign}${t.action}`, title: `${t.action === "pause" ? "Pause" : "Raise the budget of"} "${t.campaign}"`,
        subtitle: t.why ?? "Ads analyst · a person changes the ad", tag: "Suggestion", tone: "neutral" };
  }
}

/** The run counts a level only up to the role's cap; the server refuses anything higher. */
export const allowed = (lvl: Level, max: Level) => LEVELS.indexOf(lvl) <= LEVELS.indexOf(max);
