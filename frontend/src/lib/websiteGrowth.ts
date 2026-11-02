// Website phases 2-6 (backend endpoints/website_growth.py): tracking, results report, and the launch tools.
import api from "@/lib/api";

const WEB = "/websites";

export type Tracking = { pixel_id: string | null; ga4_id: string | null; capi_enabled: boolean; capi_test_code: string | null;
  has_capi_token: boolean; recent?: { event_name: string; status: string; reason: string | null; created_at: string }[] };
export type TrackingIn = { pixel_id: string | null; ga4_id: string | null; capi_enabled: boolean; capi_token?: string | null;
  capi_test_code: string | null };
export type ReportRow = { source: string; visits: number; enquiries: number; bookings: number; enquiry_rate: number | null; value?: number };
export type Report = { days: number; since: string; total: { visits: number; enquiries: number; bookings: number }; rows: ReportRow[];
  buttons: { code: string; enquiries: number; bookings: number }[]; money_restricted: boolean };

export type Promo = { id: string; code: string; kind: "percent" | "flat"; value: number; starts_on: string | null; ends_on: string | null;
  min_nights: number; max_uses: number | null; used_count: number; property_ids: string[]; label: string | null; active: boolean };
export type PromoIn = Omit<Promo, "id" | "used_count">;

export const growthApi = {
  promos: () => api.get<Promo[]>(`${WEB}/promos`).then(r => r.data),
  addPromo: (p: PromoIn) => api.post<Promo>(`${WEB}/promos`, p).then(r => r.data),
  savePromo: (id: string, p: PromoIn) => api.put<Promo>(`${WEB}/promos/${id}`, p).then(r => r.data),
  tracking: () => api.get<Tracking>(`${WEB}/tracking`).then(r => r.data),
  saveTracking: (t: TrackingIn) => api.put<Tracking>(`${WEB}/tracking`, t).then(r => r.data),
  report: (days = 30) => api.get<Report>(`${WEB}/report`, { params: { days } }).then(r => r.data),
};
