// Get found / dynamic SOPs API (backend/app/api/v1/endpoints/sops.py). Shapes are hand-written next to their use.
import api from "@/lib/api";

export const SOPS_READ_ROLES = ["owner", "manager", "marketing", "reservations", "concierge", "foh"];
export const SOPS_MANAGE_ROLES = ["owner", "manager"];

export type Platform = "google_business" | "instagram" | "whatsapp" | "facebook_page" | "airbnb" | "booking" | "makemytrip"
  | "agoda" | "tripadvisor";
export const PLATFORM_LABEL: Record<Platform, string> = {
  google_business: "Google Business Profile", instagram: "Instagram", whatsapp: "WhatsApp Business", facebook_page: "Facebook Page",
  airbnb: "Airbnb", booking: "Booking.com", makemytrip: "MakeMyTrip / Goibibo", agoda: "Agoda", tripadvisor: "TripAdvisor",
};
export const PLATFORM_ORDER = Object.keys(PLATFORM_LABEL) as Platform[];

export interface RuleRef { key: string; status: "verified" | "unverified" | "haip_advice"; as_of: string; source_url: string | null; source_note: string; stale: boolean }
export interface Category extends RuleRef { name: string; rank: number }
export interface Photo { asset_id: string; alt: string; subject: string | null; url?: string | null }
export interface Step {
  key: string; title: string; how: string; verify: "auto" | "evidence" | "manual"; check: string | null;
  link: { label: string; href: string } | null;
  /** `hidden`: a money value (discount policy) this person may not see; the text says so. */
  values: { label: string; text: string; ai?: boolean; restricted?: boolean; hidden?: boolean }[];
  needs: { label: string; href: string | null }[];
  notes: string[]; rules: RuleRef[]; categories: Category[] | null; photos: Photo[] | null; custom?: boolean;
  hidden: boolean; status: "todo" | "done" | "skipped"; changed: boolean; due_at: string | null; done_at: string | null;
  done_by: string | null; evidence: { asset_id: string | null; url: string | null } | null;
  check_result: { result: "ok" | "fail" | "unknown"; detail: string; at: string } | null;
}
export interface SopSummary {
  id: string; template_key: string; platform: Platform; title: string; recurrence: string;
  status: "active" | "paused" | "done" | "archived"; property_id: string | null; property_name: string | null; assignee_id: string | null;
  preparing: boolean; next_due_at: string | null; done: number; total: number;
}
export interface SopDetail extends SopSummary {
  summary: string; steps: Step[]; can_work: boolean;
  version: { no: number; reason: string; created_at: string | null; ai: boolean; ai_note: string | null } | null;
}
export interface Available {
  template_key: string; platform: Platform; title: string; summary: string; steps: number;
  property_id: string | null; property_name: string | null;
}

const S = "/sops";
export const sopsApi = {
  list: () => api.get<{ kind: string | null; instances: SopSummary[]; available: Available[] }>(S).then(r => r.data),
  start: (template_key: string, property_id: string | null = null) =>
    api.post<{ id: string }>(S, { template_key, property_id }).then(r => r.data),
  get: (id: string) => api.get<SopDetail>(`${S}/${id}`).then(r => r.data),
  step: (id: string, key: string, action: "done" | "skip" | "undo") =>
    api.post<SopDetail>(`${S}/${id}/steps/${key}/${action}`, {}).then(r => r.data),
  upload: (id: string, key: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post(`${S}/${id}/steps/${key}/evidence`, form).then(r => r.data);
  },
  link: (id: string, key: string, url: string) => api.post(`${S}/${id}/steps/${key}/evidence-link`, { url }).then(r => r.data),
  evidence: (id: string, key: string) => api.get<{ url: string }>(`${S}/${id}/steps/${key}/evidence`).then(r => r.data.url),
  check: (id: string) => api.post(`${S}/${id}/check`, {}).then(r => r.data),
  regenerate: (id: string) => api.post(`${S}/${id}/regenerate`, {}).then(r => r.data),
};

export const ruleWords = (r: { status: RuleRef["status"]; stale: boolean }) =>
  r.status === "unverified" ? "Not confirmed" : r.status === "haip_advice" ? "HAIP advice" : r.stale ? "May be out of date" : "Confirmed";
