// Property assessment + ROI tool (public page /assess). Types mirror backend/app/schemas/assessment.py and the
// result built by backend/app/services/assessment_engine.py (hand-written: there is no OpenAPI generator).
import { formatINR } from "@/lib/utils";
import { postPublic, type SubmitResult } from "@/lib/publicLeads";

export type PropertyType = "hotel" | "urban_retreat" | "rural_retreat" | "farmhouse" | "event_space";
export type Scenario = "low" | "likely" | "high";
export const SCENARIOS: Scenario[] = ["low", "likely", "high"];
export const SCENARIO_LABEL: Record<Scenario, string> = { low: "Low", likely: "Likely", high: "High" };
export const SQFT_PER_ACRE = 43560;

export interface AssessmentAnswers {
  plot_size: number;
  plot_unit: "sqft" | "acres";
  rooms: number;
  property_type: PropertyType;
  amenities: string[];
  experiences: string[];
  city: string;
  district?: string | null;
  landmark: "highway" | "airport" | "tourist_spot";
  landmark_km: number;
  seasonality: string;
  competitor_density: "low" | "medium" | "high";
  build_status: "new" | "conversion";
}

export interface Option { key: string; label: string }
export interface AssessmentOptions {
  benchmark_version: string;
  benchmark_label: string;
  sample: boolean;
  region: string;
  property_types: Option[];
  amenities: Option[];
  experiences: Option[];
  seasonality: Option[];
  landmarks: Option[];
  competitor_density: Option[];
  segments: { small_max_sqft: number; medium_max_sqft: number };
}

export interface Offer { title: string; text: string; price_text: string }
export interface Cta { saas: Offer; service: Offer }

export interface AssessmentSummary {
  benchmark_version: string;
  benchmark_label: string;
  benchmark_sample: boolean;
  property_type_label: string;
  segment: "small" | "medium" | "large";
  segment_label: string;
  plot_sqft: number;
  keys: number;
  location_label: string;
  warnings: string[];
  disclaimer: string;
  cta: Cta;
  yearly_revenue: Record<Scenario, number>;
  investment_total: number;
  payback_months_likely: number | null;
}

export interface YearFigures {
  revenue: number; room_revenue: number; extras_revenue: number; event_revenue: number; nights_sold: number;
  ota_commission: number; running_costs: number; net_operating_income: number; monthly_average_revenue: number;
  average_occupancy: number;
}

export interface Zone { key: string; label: string; sqft: number; pct: number; x: number; y: number; w: number; h: number }

export interface AssessmentReport extends Omit<AssessmentSummary, "yearly_revenue" | "investment_total" | "payback_months_likely"> {
  adr: number;
  running_cost_pct: number;
  ota_share: number;
  ota_commission_pct: number;
  monthly: { month: string; occupancy: Record<Scenario, number>; revenue: Record<Scenario, number> }[];
  yearly: Record<Scenario, YearFigures>;
  investment: { build_status: string; built_up_sqft: number; build_cost: number; fitout: number; amenities: number; contingency: number; total: number };
  payback_months: Record<Scenario, number | null>;
  zoning: { plot_sqft: number; width: number; height: number; fits: boolean; max_keys: number; floors: number; zones: Zone[] };
  assumptions: string[];
}

export const DEFAULT_ANSWERS: AssessmentAnswers = {
  plot_size: 1,
  plot_unit: "acres",
  rooms: 8,
  property_type: "rural_retreat",
  amenities: [],
  experiences: [],
  city: "",
  district: "",
  landmark: "tourist_spot",
  landmark_km: 10,
  seasonality: "even",
  competitor_density: "medium",
  build_status: "new",
};

export function plotSqft(a: Pick<AssessmentAnswers, "plot_size" | "plot_unit">): number {
  return a.plot_unit === "acres" ? a.plot_size * SQFT_PER_ACRE : a.plot_size;
}

/** Same rule as the backend (small < 5,000 sq ft, medium < 1 acre, large >= 1 acre); shown live as the visitor types. */
export function segmentFor(sqft: number, seg = { small_max_sqft: 5000, medium_max_sqft: SQFT_PER_ACRE }): "small" | "medium" | "large" {
  if (sqft < seg.small_max_sqft) return "small";
  if (sqft < seg.medium_max_sqft) return "medium";
  return "large";
}

/** What blocks "See my estimate", or null. Mirrors the server's bounds so most mistakes never reach it. */
export function answersProblem(a: AssessmentAnswers): string | null {
  const sqft = plotSqft(a);
  if (!Number.isFinite(sqft) || sqft < 500) return "Enter a plot of at least 500 sq ft.";
  if (sqft > 2000 * SQFT_PER_ACRE) return "The plot can be at most 2,000 acres.";
  if (!Number.isInteger(a.rooms) || a.rooms < 0 || a.rooms > 300) return "Rooms must be a whole number from 0 to 300.";
  if (a.property_type !== "event_space" && a.rooms < 1) return "Enter at least one room or unit.";
  if (a.city.trim().length < 2) return "Enter the town or city.";
  if (!Number.isFinite(a.landmark_km) || a.landmark_km < 0 || a.landmark_km > 500) return "Distance must be 0 to 500 km.";
  return null;
}

export const money = (n: number) => formatINR(n);
export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const months = (n: number | null) => (n == null ? "No payback" : `${n} months`);

export function toggle(list: string[], key: string): string[] {
  return list.includes(key) ? list.filter(k => k !== key) : [...list, key];
}

export function cleanAnswers(a: AssessmentAnswers): AssessmentAnswers {
  return { ...a, city: a.city.trim(), district: a.district?.trim() || null };
}

export function requestEstimate(a: AssessmentAnswers): Promise<SubmitResult<{ summary: AssessmentSummary }>> {
  return postPublic("/api/v1/public/assessment/estimate", cleanAnswers(a));
}

export function reportPdfUrl(id: string, token: string): string {
  return `/api/v1/public/assessment/${encodeURIComponent(id)}/report.pdf?token=${encodeURIComponent(token)}`;
}
