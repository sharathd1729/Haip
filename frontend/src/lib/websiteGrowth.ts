// Website phases 2-6 (backend endpoints/website_growth.py): tracking, results report, and the launch tools.
import api from "@/lib/api";

const WEB = "/websites";

export type Tracking = { pixel_id: string | null; ga4_id: string | null; capi_enabled: boolean; capi_test_code: string | null;
  has_capi_token: boolean; has_ga4_api_secret: boolean; ga4_server: boolean;
  recent?: { channel?: "meta" | "ga4"; event_name: string; status: string; reason: string | null; created_at: string }[] };
export type TrackingIn = { pixel_id: string | null; ga4_id: string | null; capi_enabled: boolean; capi_token?: string | null;
  capi_test_code: string | null; ga4_api_secret?: string | null };
export type ReportRow = { source: string; visits: number; enquiries: number; bookings: number; enquiry_rate: number | null; value?: number };
export type Report = { days: number; since: string; total: { visits: number; enquiries: number; bookings: number }; rows: ReportRow[];
  buttons: { code: string; enquiries: number; bookings: number }[]; money_restricted: boolean };

export type Promo = { id: string; code: string; kind: "percent" | "flat"; value: number; starts_on: string | null; ends_on: string | null;
  min_nights: number; max_uses: number | null; used_count: number; property_ids: string[]; label: string | null; active: boolean };
export type PromoIn = Omit<Promo, "id" | "used_count">;

export type Guide = { id: string; title: string; status: string; generation_status: string; generation_error: string | null;
  version_id: string | null; live: boolean; payload: { title: string; slug: string; excerpt: string; body: string; seo_description: string } | null };
export type SiteReview = { id: string; source: string; reviewer: string | null; rating: number | null; comment: string | null;
  reviewed_at: string | null; shown: boolean; consent_note: string | null };
export type LibraryItem = { id: string; ref: string; url: string; mime_type: string; duration_ms?: number | null; alt_text: string | null };

export type Lang = { code: string; name: string; live: boolean };
export type TranslateJob = { id: string; status: string; error: string | null; language: string; version_id: string | null;
  result: { translated: number; left_in_english: string[] } | null };
export type LaunchReport = {
  site: { name: string; status: string; url: string }; published: { version: number; at: string | null } | null; problem?: string;
  domain?: { host: string; kind: string; status: string; https: boolean }[];
  pages?: { title: string; path: string; sections: string[]; languages: string[] }[]; extra_pages?: string[];
  quality?: { scores: { performance: number; accessibility: number; seo: number }; to_improve: string[] };
  schema?: Record<string, string[]>;
  tracking?: { meta_pixel: boolean; ga4: boolean; conversions_api: boolean; cookie_banner: boolean; last_event_sent_at: string | null };
  booking?: { mode: string; prices_shown: boolean; razorpay_connected: boolean | null; last_booking_at: string | null;
    dry_run: { stay: string; ok: boolean; result: string }[] };
  content?: { guides_live: number; reviews_shown: number; promo_codes_on: number; languages: string[] };
  open_items?: string[];
};

export const growthApi = {
  languages: () => api.get<Lang[]>(`${WEB}/languages`).then(r => r.data),
  translate: (language: string) => api.post<TranslateJob>(`${WEB}/translate`, { language }).then(r => r.data),
  translateJob: (id: string) => api.get<TranslateJob>(`${WEB}/translate/${id}`).then(r => r.data),
  launch: () => api.get<LaunchReport>(`${WEB}/launch-report`).then(r => r.data),
  launchPdf: () => api.get<Blob>(`${WEB}/launch-report.pdf`, { responseType: "blob", timeout: 120_000 }).then(r => r.data),
  guides: () => api.get<Guide[]>(`${WEB}/blog`).then(r => r.data),
  writeGuide: (topic: string) => api.post<Guide>(`${WEB}/blog`, { topic }).then(r => r.data),
  editGuide: (id: string, payload: NonNullable<Guide["payload"]>) => api.put<Guide>(`${WEB}/blog/${id}`, { payload }).then(r => r.data),
  guideAction: (id: string, action: "submit" | "approve" | "reject" | "archive", version_id: string) =>
    api.post<Guide>(`${WEB}/blog/${id}/${action}`, { version_id }).then(r => r.data),
  reviews: () => api.get<SiteReview[]>(`${WEB}/reviews`).then(r => r.data),
  reviewConsent: (id: string, note: string | null) => api.put<SiteReview[]>(`${WEB}/reviews/${id}/consent`, { note }).then(r => r.data),
  importReviews: () => api.post(`${WEB}/reviews/import`).then(r => r.data),
  importMedia: (file: File, origin: "upload" | "canva", alt?: string) => {
    const f = new FormData();
    f.append("file", file);
    f.append("origin", origin);
    if (alt) f.append("alt_text", alt);
    return api.post<LibraryItem>(`${WEB}/media/import`, f).then(r => r.data);
  },
  promos: () => api.get<Promo[]>(`${WEB}/promos`).then(r => r.data),
  addPromo: (p: PromoIn) => api.post<Promo>(`${WEB}/promos`, p).then(r => r.data),
  savePromo: (id: string, p: PromoIn) => api.put<Promo>(`${WEB}/promos/${id}`, p).then(r => r.data),
  tracking: () => api.get<Tracking>(`${WEB}/tracking`).then(r => r.data),
  saveTracking: (t: TrackingIn) => api.put<Tracking>(`${WEB}/tracking`, t).then(r => r.data),
  report: (days = 30) => api.get<Report>(`${WEB}/report`, { params: { days } }).then(r => r.data),
};
