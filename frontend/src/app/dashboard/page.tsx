import { redirect } from "next/navigation";

// Owner Dashboard deactivated 2026-08-08 -- being rebuilt from scratch
// (backend router-level require_module("analytics") 403s GET /dashboard
// anyway). Every login flow redirects here, so this can't just disappear --
// send users to Leads360, the flagship active pipeline view, instead.
// DashboardOverview component + backend endpoint are untouched, restore
// this page once the rebuild ships.
export default function DashboardPage() {
  redirect("/dashboard/leads");
}
