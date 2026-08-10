import { redirect } from "next/navigation";

// Owner Dashboard widget builder deactivated 2026-08-08 -- being rebuilt
// from scratch (backend router-level require_module("analytics") 403s
// every /dashboards endpoint anyway). No nav link points here anymore;
// this only catches a stale bookmark/direct URL. Original client
// component + backend endpoints are untouched, restore this page once
// the rebuild ships.
export default function MyDashboardsPage() {
  redirect("/dashboard/leads");
}
