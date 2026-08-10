import { redirect } from "next/navigation";

// "Charts" (analytics forecasting/intelligence charts) deactivated
// 2026-08-08 -- being rebuilt from scratch. No nav link points here
// anymore; this only catches a stale bookmark/direct URL. "Exports" at
// /dashboard/reports (the sibling page) is untouched -- that's raw report
// generation, not analytics. Original client component + backend
// endpoints are untouched, restore this page once the rebuild ships.
export default function ReportsAnalyticsPage() {
  redirect("/dashboard/reports");
}
