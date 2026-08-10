import { redirect } from "next/navigation";

// Executive Dashboard / analytics pages deactivated 2026-08-08 -- being
// rebuilt from scratch (backend router-level require_module("analytics")
// 403s every /analytics/executive, /analytics/guests, /analytics/channels
// etc. endpoint anyway). No nav link points here anymore; this only
// catches a stale bookmark/direct URL. Original client component +
// backend endpoints are untouched, restore this page once the rebuild
// ships.
export default function AnalyticsPage() {
  redirect("/dashboard/leads");
}
