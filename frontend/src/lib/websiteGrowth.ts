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

export const growthApi = {
  tracking: () => api.get<Tracking>(`${WEB}/tracking`).then(r => r.data),
  saveTracking: (t: TrackingIn) => api.put<Tracking>(`${WEB}/tracking`, t).then(r => r.data),
  report: (days = 30) => api.get<Report>(`${WEB}/report`, { params: { days } }).then(r => r.data),
};
